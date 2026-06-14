"""Chat API."""

from __future__ import annotations

from fastapi import APIRouter

from backend.app.config import settings
from backend.app.rag.answer_generator import AnswerGenerator
from backend.app.retrieval.elastic_searcher import HybridSearcher
from backend.app.retrieval.graph_store import GraphExpander
from backend.app.retrieval.query_analyzer import QueryAnalyzer
from backend.app.schemas import ChatRequest, ChatResponse
from backend.app.storage.elastic import KnowledgeIndex


router = APIRouter(prefix="/api", tags=["chat"])


@router.post("/chat", response_model=ChatResponse)
def chat(request: ChatRequest) -> dict:
    """Answer a branch-support question."""
    analyzer = QueryAnalyzer()
    intent = analyzer.analyze(
        request.question,
        screen_id=request.screen_id,
        screen_name=request.screen_name,
    )
    searcher = HybridSearcher()
    ranked = searcher.search(intent, user_role=request.user_role, top_k=12)
    seed_docs = [doc for doc, _ in ranked]
    all_docs = KnowledgeIndex().load_documents()
    docs = GraphExpander().expand(seed_docs, all_docs)[:12]
    response = AnswerGenerator().generate(
        question=request.question,
        docs=docs,
        user_role=request.user_role,
        use_llm=settings.enable_llm_chat,
    )
    if not request.include_sources:
        response["sources"] = []
    return response
