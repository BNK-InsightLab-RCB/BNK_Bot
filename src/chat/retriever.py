"""Chat domain — retrieval. Question → top-k chunks from Qdrant.

Thin wrapper that reuses the ingestion-side infra (``Embedder`` + ``QdrantStore``)
for the READ path. Held as a singleton in ``app.state`` (built once at startup
in ``main.lifespan``) so the heavy KURE model is loaded only once.
"""
from __future__ import annotations

from src.config import settings
from src.ingestion.embedder import Embedder
from src.ingestion.qdrant import QdrantStore


class Retriever:
    """질문 → top-k 근거 청크.

    ``score_threshold`` 를 항상 적용한다(기본 ``settings.retrieval_score_threshold``).
    이게 **"모르면 모른다"의 결정론적 절반**이다 — 임계 아래면 빈 리스트가 되고
    ``ChatService`` 가 LLM 호출 없이 즉시 거부한다. 임계가 없던 시절엔 무관 질문에도
    항상 5청크가 붙어 나가서, 거부 여부가 전적으로 모델 판단에 맡겨져 있었다.
    """

    def __init__(self, embedder: Embedder, store: QdrantStore,
                 score_threshold: float | None = None):
        self.embedder = embedder
        self.store = store
        self.score_threshold = (
            settings.retrieval_score_threshold if score_threshold is None else score_threshold
        )

    def retrieve(
        self,
        question: str,
        top_k: int = 5,
        category: str | None = None,
        product: str | None = None,
        doc_type: str | None = None,
        score_threshold: float | None = None,
    ):
        """Return Qdrant ScoredPoints (payload + score) for the question.

        Optional exact-match payload filters (category/doc_type are folder-derived
        values like 예금/설명서; product must match stored product_name exactly).
        ``score_threshold`` 를 명시하면 이번 호출만 다른 하한을 쓴다(보정·측정용).
        """
        flt = QdrantStore.build_filter(
            category=category, product_name=product, doc_type=doc_type
        )
        query_vec = self.embedder.embed_query(question)
        return self.store.search(
            query_vec, top_k=top_k, flt=flt,
            score_threshold=self.score_threshold if score_threshold is None else score_threshold,
        )
