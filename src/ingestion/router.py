"""Ingestion(admin) domain controller (E6). 고객 `/query` 와 라우터 분리.

`/admin/ingest` 로 기존 적재 파이프라인을 **비동기** 트리거하고 상태를 조회한다.
실제 로직은 ``JobRegistry`` 에 위임 — 컨트롤러는 요청 수신·DI·HTTP 매핑만.
(인증은 SpringBoot 연동 단계에서; 여기선 라우터 분리까지.)
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request

from src.ingestion.jobs import IngestRootError, JobConflictError, JobRegistry
from src.ingestion.schemas import IngestJob, IngestRequest

router = APIRouter(prefix="/admin", tags=["admin"])


def get_jobs(request: Request) -> JobRegistry:
    """싱글톤 JobRegistry 를 app.state 에서 주입."""
    return request.app.state.ingest_jobs


@router.post("/ingest", response_model=IngestJob, status_code=202)
def start_ingest(req: IngestRequest, jobs: JobRegistry = Depends(get_jobs)) -> IngestJob:
    """적재 시작 → 즉시 job 반환(202).

    400 = root 가 허용 경계(`settings.data_root`) 밖 / 409 = 이미 진행 중.
    컬렉션 재생성(`recreate`)은 이 API 로 불가 — CLI 전용(schemas 주석 참조).
    """
    try:
        job = jobs.start(root=req.root, limit=req.limit)
    except IngestRootError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except JobConflictError as e:
        raise HTTPException(status_code=409, detail=str(e))
    return IngestJob(**job)


@router.get("/ingest/{job_id}", response_model=IngestJob)
def get_ingest(job_id: str, jobs: JobRegistry = Depends(get_jobs)) -> IngestJob:
    job = jobs.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"job not found: {job_id}")
    return IngestJob(**job)


@router.get("/ingest")
def list_ingest(jobs: JobRegistry = Depends(get_jobs)) -> dict:
    """현재 활성 job + 최근 job 목록(최신순)."""
    return jobs.list()
