from __future__ import annotations

import argparse
import sys
from pathlib import Path

from tqdm import tqdm

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import ROOT_DIR, get_settings
from rag.chunker import chunk_markdown_directory, write_chunks_jsonl
from rag.elastic_index import bulk_index_chunks, create_client, ensure_index, recreate_index
from rag.embedder import KureEmbedder
from rag.pdf_to_markdown import convert_pdf_directory


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Ingest PDFs into Elasticsearch for BNK_Bot RAG PoC.")
    parser.add_argument("--pdf-dir", default=str(ROOT_DIR / "data/raw_pdfs"))
    parser.add_argument("--markdown-dir", default=str(ROOT_DIR / "data/markdown"))
    parser.add_argument("--chunks-file", default=str(ROOT_DIR / "data/chunks/chunks.jsonl"))
    parser.add_argument("--recreate-index", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    settings = get_settings()

    pdf_dir = Path(args.pdf_dir)
    markdown_dir = Path(args.markdown_dir)
    chunks_file = Path(args.chunks_file)

    if not pdf_dir.exists():
        raise SystemExit(f"PDF directory does not exist: {pdf_dir}")

    pdf_paths = sorted(pdf_dir.glob("*.pdf"))
    if not pdf_paths:
        raise SystemExit(f"No PDF files found in: {pdf_dir}")

    print(f"Converting {len(pdf_paths)} PDF file(s) to Markdown...")
    markdown_paths = convert_pdf_directory(pdf_dir, markdown_dir)
    print(f"Markdown files written: {len(markdown_paths)}")

    print("Chunking Markdown files...")
    chunks = chunk_markdown_directory(markdown_dir, settings.chunk_size, settings.chunk_overlap)
    if not chunks:
        raise SystemExit("No chunks were generated. Check PDF text extraction results.")
    write_chunks_jsonl(chunks, chunks_file)
    print(f"Chunks written: {chunks_file} ({len(chunks)} chunks)")

    print("Loading KURE-v1 embedder...")
    embedder = KureEmbedder(settings.kure_model_path)

    print("Embedding chunks...")
    chunk_dicts = [chunk.to_dict() for chunk in chunks]
    embeddings = embedder.encode([chunk.content for chunk in tqdm(chunks)], batch_size=16)

    client = create_client(settings.elasticsearch_url)
    if args.recreate_index:
        print(f"Recreating Elasticsearch index: {settings.elasticsearch_index}")
        recreate_index(client, settings.elasticsearch_index, settings.embedding_dim)
    else:
        ensure_index(client, settings.elasticsearch_index, settings.embedding_dim)

    print("Indexing chunks into Elasticsearch...")
    bulk_index_chunks(client, settings.elasticsearch_index, chunk_dicts, embeddings)
    print("Done.")


if __name__ == "__main__":
    main()

