from __future__ import annotations

from fastapi import APIRouter, Request

from app.deps import get_elasticsearch_client, get_embedder
from app.schemas import SearchRequest, SearchResponse, SearchResultItem
from rag.hybrid_search import HybridSearcher


router = APIRouter(tags=["search"])


@router.post("/search", response_model=SearchResponse)
def search(request: Request, payload: SearchRequest) -> SearchResponse:
    settings = request.app.state.settings
    searcher = HybridSearcher(
        get_elasticsearch_client(request),
        settings.elasticsearch_index,
        get_embedder(request),
    )
    results = searcher.search(payload.query, bm25_k=payload.bm25_k, vector_k=payload.vector_k, top_k=payload.top_k)
    return SearchResponse(
        query=payload.query,
        results=[
            SearchResultItem(
                chunk_id=str(result["chunk_id"]),
                doc_id=str(result["doc_id"]),
                title=str(result["title"]),
                section=str(result["section"]),
                source_file=str(result["source_file"]),
                rrf_score=float(result["rrf_score"]),
                raw_score=float(result["raw_score"]),
                preview=" ".join(str(result["content"]).split())[:300],
            )
            for result in results
        ],
    )

