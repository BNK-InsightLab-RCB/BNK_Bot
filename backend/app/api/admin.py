"""Admin and health API."""

from __future__ import annotations

from fastapi import APIRouter

from backend.app.config import settings
from backend.app.schemas import HealthResponse
from backend.app.storage.elastic import KnowledgeIndex


router = APIRouter(prefix="/api", tags=["admin"])


@router.get("/health", response_model=HealthResponse)
def health() -> dict:
    """Return backend health."""
    return {"status": "ok", "index_name": settings.elastic_index}


@router.post("/admin/reset")
def reset_index() -> dict:
    """Reset local and Elasticsearch indexes."""
    KnowledgeIndex().reset()
    return {"status": "reset"}
