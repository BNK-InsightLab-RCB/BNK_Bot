"""Chat domain controller (FastAPI router). Spring 의 @RestController 역할.

E2: ``/query`` 가 실제 검색을 수행해 출처(sources)를 반환한다. 답변 문장 생성
(Qwen)·가드레일은 E3~E5에서 ``service`` 계층으로 붙인다.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Request

from src.chat.retriever import Retriever
from src.chat.schemas import QueryRequest, QueryResponse, Source

router = APIRouter(tags=["chat"])

_ANSWER_PLACEHOLDER = "(E2: 검색만 동작 — 답변 생성은 E3~E4(Qwen)에서 추가됩니다.)"


def get_retriever(request: Request) -> Retriever:
    """싱글톤 Retriever를 app.state에서 주입 (Spring DI 대응)."""
    return request.app.state.retriever


@router.post("/query", response_model=QueryResponse)
def query(req: QueryRequest, retriever: Retriever = Depends(get_retriever)) -> QueryResponse:
    hits = retriever.retrieve(
        req.question,
        top_k=req.top_k,
        category=req.category,
        product=req.product,
        doc_type=req.doc_type,
    )
    sources = [
        Source(
            product_name=h.payload.get("product_name", ""),
            doc_type=h.payload.get("doc_type", ""),
            page=h.payload.get("page", 0),
            section=h.payload.get("section", ""),
            snippet=(h.payload.get("body", "") or "").replace("\n", " ")[:200],
            score=round(h.score, 3),
        )
        for h in hits
    ]
    return QueryResponse(
        answer=_ANSWER_PLACEHOLDER,
        sources=sources,
        used_chunks=len(sources),
    )
