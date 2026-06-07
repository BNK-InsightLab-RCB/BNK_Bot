"""End-to-end ingestion orchestration: PDF → MD → chunks → vectors → Qdrant.

Glue only — wires parser / processor / embedder / qdrant together. Heavy
resources (the KURE model, the Qdrant client) are created once and reused across
documents (loading KURE per file would be ruinous for a 489-doc batch).
Per-document failures are isolated (logged + quarantined to ``failed/``) so a
batch never aborts midway. Re-ingesting a document overwrites (deterministic
point ids), so runs are idempotent.

Three layers:
- ``ingest_document``  : one PDF.
- ``ingest_paths``     : a list of PDFs (creates/reuses resources, loops).
- ``ingest_directory`` : every PDF under a directory tree (rglob, recursive).

category/doc_type come from the folder layout ``.../{category}/{doc_type}/x.pdf``
so pointing the batch at ``Data_PDF/`` tags every file correctly with no map.
"""
from __future__ import annotations

import shutil
from dataclasses import asdict
from pathlib import Path

from loguru import logger

from src.config import settings
from src.ingestion.embedder import Embedder
from src.ingestion.parser import PDFParser
from src.ingestion.processor import chunk_md_file, write_chunks
from src.ingestion.qdrant import QdrantStore


def derive_metadata(pdf_path: Path) -> tuple[str, str]:
    """(category, doc_type) from layout: .../{category}/{doc_type}/file.pdf"""
    return pdf_path.parent.parent.name, pdf_path.parent.name


def ingest_document(
    pdf_path: str | Path,
    parser: PDFParser,
    embedder: Embedder,
    store: QdrantStore,
) -> dict:
    """Process ONE pdf end-to-end. Assumes the collection already exists."""
    pdf_path = Path(pdf_path)
    category, doc_type = derive_metadata(pdf_path)

    md_path = parser.parse(pdf_path)                                   # 1. PDF→MD
    chunks = chunk_md_file(md_path, category=category, doc_type=doc_type)  # 2. chunk
    write_chunks(chunks, settings.chunks_dir / f"{pdf_path.stem}.jsonl")
    vectors = embedder.embed_texts([c.text for c in chunks])           # 3. embed
    store.upsert_chunks([asdict(c) for c in chunks], vectors)          # 4. upsert
    return {
        "file": pdf_path.name,
        "category": category,
        "doc_type": doc_type,
        "chunks": len(chunks),
    }


def _make_resources(recreate: bool) -> tuple[PDFParser, Embedder, QdrantStore]:
    parser = PDFParser(settings.processed_dir)
    embedder = Embedder()
    store = QdrantStore(
        url=settings.qdrant_url,
        collection=settings.qdrant_collection_name,
        dim=embedder.dim,
        api_key=settings.qdrant_api_key,
    )
    store.ensure_collection(recreate=recreate)
    return parser, embedder, store


def ingest_paths(
    paths,
    *,
    recreate: bool = False,
    parser: PDFParser | None = None,
    embedder: Embedder | None = None,
    store: QdrantStore | None = None,
) -> dict:
    """Process a list of PDFs, reusing one model + client. Failures are isolated."""
    paths = [Path(p) for p in paths]
    if parser is None or embedder is None or store is None:
        parser, embedder, store = _make_resources(recreate)

    ok: list[dict] = []
    failed: list[dict] = []
    for i, p in enumerate(paths, 1):
        try:
            res = ingest_document(p, parser, embedder, store)
            ok.append(res)
            logger.success(f"[{i}/{len(paths)}] {p.name} → {res['chunks']} chunks")
        except Exception as e:  # isolate: one bad PDF must not stop the batch
            logger.error(f"[{i}/{len(paths)}] FAILED {p.name}: {e}")
            failed.append({"file": p.name, "error": str(e)})
            try:
                settings.failed_dir.mkdir(parents=True, exist_ok=True)
                shutil.copy2(p, settings.failed_dir / p.name)
            except Exception:
                pass

    summary = {
        "ok": len(ok),
        "failed": len(failed),
        "total": len(paths),
        "chunks": sum(r["chunks"] for r in ok),
        "points_in_collection": store.count(),
        "failures": failed,
    }
    logger.info(
        f"ingest done: ok={summary['ok']} failed={summary['failed']} "
        f"chunks={summary['chunks']} points={summary['points_in_collection']}"
    )
    return summary


def ingest_directory(root: str | Path, *, recreate: bool = False, pattern: str = "*.pdf") -> dict:
    """Ingest every PDF under ``root`` (recursively, incl. subfolders)."""
    root = Path(root)
    pdfs = sorted(root.rglob(pattern))
    logger.info(f"found {len(pdfs)} PDFs under {root}")
    return ingest_paths(pdfs, recreate=recreate)


if __name__ == "__main__":
    # Verification: one 설명서 (lattice path) + one 약관 (Docling fallback path).
    data = Path("/Users/jhyeong/Project/InsightLab/Data_PDF")
    s1 = next((p for p in (data / "예금" / "설명서").glob("*.pdf")
               if "마이플랜퇴직연금정기예금" in p.name), None)
    s2 = next(iter(sorted((data / "예금" / "약관").glob("*.pdf"))), None)
    samples = [p for p in (s1, s2) if p]

    summary = ingest_paths(samples, recreate=True)
    print("\n=== summary ===")
    for r in summary.pop("failures"):
        print("  FAIL:", r)
    print(summary)
