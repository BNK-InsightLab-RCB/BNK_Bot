"""Chat domain DTOs (request/response). FastAPI's equivalent of Spring DTOs."""
from __future__ import annotations

from pydantic import BaseModel, Field


class QueryRequest(BaseModel):
    question: str = Field(..., min_length=1, description="고객 질문")
    top_k: int = Field(5, ge=1, le=20, description="검색할 청크 수")
    # optional payload filters (Qdrant) — 상품/카테고리/문서종류 한정 검색
    category: str | None = None
    product: str | None = None
    doc_type: str | None = None


class Source(BaseModel):
    """답변 근거(출처) — payload에서 채움. 환각 검증·인용 표시에 사용."""

    product_name: str
    doc_type: str
    page: int
    section: str
    snippet: str
    score: float


class QueryResponse(BaseModel):
    answer: str
    sources: list[Source] = []
    used_chunks: int = 0
