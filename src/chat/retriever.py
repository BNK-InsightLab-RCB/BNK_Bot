"""Chat domain — retrieval. Question → top-k chunks from Qdrant.

Thin wrapper that reuses the ingestion-side infra (``Embedder`` + ``QdrantStore``)
for the READ path. Held as a singleton in ``app.state`` (built once at startup
in ``main.lifespan``) so the heavy KURE model is loaded only once.
"""
from __future__ import annotations

from src.ingestion.embedder import Embedder
from src.ingestion.qdrant import QdrantStore


class Retriever:
    def __init__(self, embedder: Embedder, store: QdrantStore):
        self.embedder = embedder
        self.store = store

    def retrieve(
        self,
        question: str,
        top_k: int = 5,
        category: str | None = None,
        product: str | None = None,
        doc_type: str | None = None,
    ):
        """Return Qdrant ScoredPoints (payload + score) for the question.

        Optional exact-match payload filters (category/doc_type are folder-derived
        values like 예금/설명서; product must match stored product_name exactly).
        """
        flt = QdrantStore.build_filter(
            category=category, product_name=product, doc_type=doc_type
        )
        query_vec = self.embedder.embed_query(question)
        return self.store.search(query_vec, top_k=top_k, flt=flt)
