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

import hashlib
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


def find_documents(root: str | Path) -> list[Path]:
    """``root`` 아래의 처리 가능한 원본 문서를 재귀 수집(정렬).

    ⚠️ 원래 ``*.pdf`` 만 훑었는데, 이 때문에 **개정후 약관이 docx 로만 존재하는
    문서를 파이프라인이 아예 인지하지 못하고 폐지된 `(개정전)` PDF 만 적재**되는
    일이 실제로 있었다(계좌통합관리서비스 이용약관). 적재 실패로도 안 잡히는
    '미인지' 유형이라 로그만 봐서는 발견되지 않는다 → 지원 포맷 전체를 훑는다.

    같은 이유로 **확장자 대소문자도 무시**한다. `rglob("*.pdf")` 는 POSIX 에서
    대소문자를 가려 `.PDF` 파일 6건(펀드/약관)을 통째로 놓치고 있었다 — 역시
    실패가 아니라 '미인지'라 로그에 흔적이 남지 않는다.

    숨김/리소스 파일(`.DS_Store`, `._foo`)은 제외한다.

    마지막으로 **내용이 같은 사본을 제거**한다(내용 해시 기준). 실측상 펀드 약관
    326건 중 172건(53%)이 `이름(1).pdf` 형태의 **바이트 단위 동일 사본**이었고,
    113개 사본 그룹 전부가 100% 일치했다. 사본을 그대로 넣으면
      · 적재 시간이 두 배로 들고
      · **top-k 자리를 같은 문장이 나눠 먹어** 근거 다양성이 줄어든다
        (실제로 검색 시 top-1/top-2 가 동일 청크로 나오는 것을 관찰).
    이름이 아니라 **내용**으로 판정하므로, 사본처럼 보이지만 내용이 다른 파일은
    그대로 남는다(이름 기반 제거는 위험해서 쓰지 않는다).
    """
    root = Path(root)
    sufs = {s.lower() for s in PDFParser.SUPPORTED_SUFFIXES}
    files = sorted(
        p for p in root.rglob("*")
        if p.is_file() and not p.name.startswith(".") and p.suffix.lower() in sufs
    )

    seen: dict[str, Path] = {}
    for p in files:
        try:
            digest = hashlib.md5(p.read_bytes()).hexdigest()
        except OSError:          # 읽기 실패는 여기서 거르지 않는다 — parser 가 사유를 진단
            seen[f"unreadable:{p}"] = p
            continue
        prev = seen.get(digest)
        # 사본 중에서는 **이름이 짧은 쪽**을 정본으로 삼는다("X.pdf" > "X(1).pdf").
        if prev is None or (len(p.name), p.name) < (len(prev.name), prev.name):
            seen[digest] = p

    dropped = len(files) - len(seen)
    if dropped:
        logger.info(f"deduplicated {dropped} identical copies ({len(files)} → {len(seen)} documents)")
    return sorted(seen.values())


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
        finally:
            # 문서 1건이 끝날 때마다 가속기 캐시를 반환한다. 안 하면 캐시가 단조 증가해
            # 배치 후반에 OOM 이 난다(실측: 58건째 MPS 12.14GiB 누적으로 2건 실패).
            # finally 라서 실패한 문서 뒤에도 반드시 비운다 — OOM 직후가 가장 위험하다.
            embedder.release_cache()

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


def ingest_directory(root: str | Path, *, recreate: bool = False) -> dict:
    """Ingest every supported document under ``root`` (recursive, incl. docx)."""
    root = Path(root)
    docs = find_documents(root)
    logger.info(f"found {len(docs)} documents under {root}")
    return ingest_paths(docs, recreate=recreate)


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
