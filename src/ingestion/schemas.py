"""Ingestion(admin) domain DTOs. chat/schemas.py 와 대칭."""
from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class IngestRequest(BaseModel):
    """적재 트리거 요청.

    ⚠️ **`recreate` 는 의도적으로 없다.** 컬렉션 전체 삭제(`delete_collection`)는
    HTTP 로 노출하지 않는다 — 무인증 상태에서 요청 한 번에 전량이 소실될 수 있고,
    시연 중 오조작으로도 터진다. 재생성이 필요하면 CLI 전용:
    ``python scripts/run_ingestion.py --recreate``.

    `root` 는 ``settings.data_root`` **하위로 제한**된다(임의 경로 스캔 차단).
    """

    # extra="forbid": 옛 클라이언트가 `recreate: true` 를 보내면 **조용히 무시하지 않고**
    # 422 로 거절한다 — "먹힌 줄 알았는데 아니었다" 가 가장 나쁜 실패라서.
    model_config = ConfigDict(extra="forbid")

    root: str | None = Field(
        None, description="적재할 디렉토리. settings.data_root 하위여야 함(기본: data_root 전체)"
    )
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
