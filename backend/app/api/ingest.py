"""Ingestion API."""

from __future__ import annotations

from fastapi import APIRouter

from backend.app.ingestion.pipeline import IngestionPipeline
from backend.app.schemas import IngestRequest, IngestResponse
from backend.app.storage.elastic import KnowledgeIndex


router = APIRouter(prefix="/api/ingest", tags=["ingest"])

_last_status = {"status": "idle", "indexed_count": 0}


@router.post("/run", response_model=IngestResponse)
def run_ingest(request: IngestRequest) -> dict:
    """Run source ingestion."""
    global _last_status
    _last_status = {"status": "running", "indexed_count": 0}
    result = IngestionPipeline().run(
        source_dir=request.source_dir,
        reset_index=request.reset_index,
        generate_summaries=request.generate_summaries,
    )
    _last_status = {"status": "completed", "indexed_count": result.indexed_count}
    return _last_status


@router.get("/status")
def ingest_status() -> dict:
    """Return last ingestion status."""
    docs = KnowledgeIndex().load_documents()
    return {**_last_status, "local_index_count": len(docs)}
