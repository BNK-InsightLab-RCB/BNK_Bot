"""Search API."""

from __future__ import annotations

from fastapi import APIRouter

from backend.app.parsers.base import KnowledgeDocument
from backend.app.rag.safety import sanitize_answer, sanitize_source
from backend.app.retrieval.elastic_searcher import HybridSearcher
from backend.app.retrieval.query_analyzer import QueryAnalyzer
from backend.app.schemas import SearchRequest, SearchResponse


router = APIRouter(prefix="/api", tags=["search"])


@router.post("/search", response_model=SearchResponse)
def search(request: SearchRequest) -> dict:
    """Run hybrid search."""
    intent = QueryAnalyzer().analyze(request.query)
    ranked = HybridSearcher().search(
        intent,
        user_role=request.user_role,
        filters=request.filters,
        top_k=request.top_k,
    )
    return {
        "results": [
            _serialize_search_result(doc, score, request.user_role)
            for doc, score in ranked
        ]
    }


def _serialize_search_result(doc: KnowledgeDocument, score: float, user_role: str) -> dict:
    """Serialize search results without exposing source internals to branch users."""
    safe_doc = sanitize_source(doc, user_role)
    if user_role == "branch":
        summary = str(safe_doc.get("reason", "업무 처리 근거를 확인했습니다."))
        business_rules = _branch_safe_rules(doc)
    else:
        summary = sanitize_answer(doc.summary, user_role)
        business_rules = [sanitize_answer(rule, user_role) for rule in doc.business_rules]
    return {
        "score": score,
        "document": safe_doc,
        "summary": summary,
        "business_rules": business_rules,
        "retrieval_backend": doc.metadata.get("retrieval_backend", "local_json"),
        "elastic_score": doc.metadata.get("elastic_score"),
    }


def _branch_safe_rules(doc: KnowledgeDocument) -> list[str]:
    """Return branch-facing rule snippets derived from source analysis."""
    rules = []
    if doc.branch_guide:
        rules.append(sanitize_answer(doc.branch_guide, "branch"))
    for message in doc.error_messages:
        rules.append(f"'{sanitize_answer(message, 'branch')}' 메시지가 표시되면 관련 입력값과 거래 상태를 확인합니다.")
    if not rules and doc.doc_type == "business_logic":
        rules.append("업무 처리 과정에서 권한, 계좌 상태, 잔액, 한도, 인증 조건을 확인합니다.")
    if not rules and doc.doc_type == "sql_mapper":
        rules.append("업무 데이터 조회 조건에 맞지 않으면 대상 거래나 계좌가 조회되지 않을 수 있습니다.")
    return rules[:5]
