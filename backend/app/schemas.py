"""API schemas."""

from __future__ import annotations

from typing import Dict, List, Optional

from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    """Chat request body."""

    question: str
    user_role: str = Field(default="branch", pattern="^(branch|it|admin)$")
    screen_id: Optional[str] = None
    screen_name: Optional[str] = None
    include_sources: bool = True


class ChatResponse(BaseModel):
    """Chat response body."""

    answer: str
    branch_guide: Dict[str, object]
    it_summary: Dict[str, object]
    confidence: float
    sources: List[Dict[str, object]]


class SearchRequest(BaseModel):
    """Search request body."""

    query: str
    user_role: str = Field(default="branch", pattern="^(branch|it|admin)$")
    filters: Dict[str, object] = Field(default_factory=dict)
    top_k: int = 10


class SearchResponse(BaseModel):
    """Search response body."""

    results: List[Dict[str, object]]


class IngestRequest(BaseModel):
    """Ingest request body."""

    source_dir: str = "backend/examples/bank_sample"
    reset_index: bool = True
    generate_summaries: bool = False


class IngestResponse(BaseModel):
    """Ingest response body."""

    status: str
    indexed_count: int


class HealthResponse(BaseModel):
    """Health response."""

    status: str
    index_name: str
