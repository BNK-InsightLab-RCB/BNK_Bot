"""Chat domain controller (FastAPI router). Spring 의 @RestController 역할.

E1: 골격 스텁. 실제 검색(E2)·Qwen 생성(E3~E4)·가드레일(E5)은 이후 단계에서
``service.py``를 통해 채운다. 지금은 라우팅/스키마/서버 기동만 검증.
"""
from __future__ import annotations

from fastapi import APIRouter

from src.chat.schemas import QueryRequest, QueryResponse

router = APIRouter(tags=["chat"])


@router.post("/query", response_model=QueryResponse)
def query(req: QueryRequest) -> QueryResponse:
    # TODO(E2~E5): service.answer(req) — 검색 → 프롬프트 → Qwen → 출처/가드레일
    return QueryResponse(
        answer=f"(stub) 질문 받음: {req.question}",
        sources=[],
        used_chunks=0,
    )
