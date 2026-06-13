"""Chat domain controller (FastAPI router). Spring 의 @RestController 역할.

E4: ``/query`` 가 검색→Qwen 답변 생성까지의 RAG 슬라이스를 수행한다. 실제 로직은
``ChatService`` (오케스트레이션)에 위임하고, 컨트롤러는 요청 수신·DI·응답만 담당한다.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Request

from src.chat.schemas import QueryRequest, QueryResponse
from src.chat.service import ChatService

router = APIRouter(tags=["chat"])


def get_chat_service(request: Request) -> ChatService:
    """싱글톤 ChatService 를 app.state 에서 주입 (Spring DI 대응)."""
    return request.app.state.chat_service


@router.post("/query", response_model=QueryResponse)
def query(
    req: QueryRequest, service: ChatService = Depends(get_chat_service)
) -> QueryResponse:
    return service.answer(req)
