"""Ingestion(admin) domain DTOs. chat/schemas.py 와 대칭."""
from __future__ import annotations

from pydantic import BaseModel, Field


class IngestRequest(BaseModel):
    """적재 트리거 요청. 전부 선택 — CLI(run_ingestion.py)와 동일 의미."""

    root: str | None = Field(None, description="적재할 디렉토리(기본: settings.raw_dir)")
    recreate: bool = Field(False, description="컬렉션을 비우고 재생성 후 적재")
    limit: int | None = Field(None, ge=1, description="앞 N개 PDF만(스모크 테스트)")


class IngestJob(BaseModel):
    """비동기 적재 job 상태. running → done(summary) | failed(error)."""

    job_id: str
    status: str  # running | done | failed
    root: str
    recreate: bool
    limit: int | None = None
    started_at: str
    finished_at: str | None = None
    summary: dict | None = None  # ingest_paths 반환(ok/failed/chunks/points...)
    error: str | None = None
