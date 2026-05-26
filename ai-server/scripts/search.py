from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import get_settings
from rag.elastic_index import create_client
from rag.embedder import KureEmbedder
from rag.hybrid_search import HybridSearcher


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run BNK_Bot hybrid search.")
    parser.add_argument("query", help="Search query")
    parser.add_argument("--top-k", type=int, default=10)
    parser.add_argument("--bm25-k", type=int, default=20)
    parser.add_argument("--vector-k", type=int, default=20)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    settings = get_settings()

    client = create_client(settings.elasticsearch_url)
    embedder = KureEmbedder(settings.kure_model_path)
    searcher = HybridSearcher(client, settings.elasticsearch_index, embedder)
    results = searcher.search(args.query, bm25_k=args.bm25_k, vector_k=args.vector_k, top_k=args.top_k)

    print(f"Query: {args.query}\n")
    for index, result in enumerate(results, start=1):
        preview = " ".join(str(result["content"]).split())[:300]
        print(f"[{index}] rrf_score={result['rrf_score']:.6f} raw_score={result['raw_score']:.6f}")
        print(f"chunk_id: {result['chunk_id']}")
        print(f"doc_id: {result['doc_id']}")
        print(f"title: {result['title']}")
        print(f"section: {result['section']}")
        print(f"source_file: {result['source_file']}")
        print("preview:")
        print(f"{preview}...")
        print()


if __name__ == "__main__":
    main()

