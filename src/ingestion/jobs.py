"""Async ingestion job registry (E6).

적재(`pipeline.ingest_*`)는 동기·블로킹·장기작업(~20분)이라 요청 스레드에서 돌리면
엔진이 멈춘다. 그래서 각 job 을 **별도 스레드**에서 돌리고 상태만 여기에 in-memory 로
기록한다 → POST 는 즉시 job_id 를 돌려주고, GET 으로 진행을 조회한다.

정책:
- **동시 1개만**(single active job): 적재 2개 동시 = 자원/`recreate` 충돌 → 진행 중이면
  ``JobConflictError``(라우터에서 409). Lock 으로 활성 job 불변식을 지킨다.
- **자원 격리**: 적재 스레드는 ``pipeline._make_resources`` 로 자체 KURE/Qdrant 를
  새로 만든다(chat 싱글톤과 분리) → ``/query`` 와 동시 실행해도 모델 객체 충돌 없음.
- **휘발성**: 기록은 in-memory(재시작 시 소실). 단일 프로세스 dev/온프렘엔 충분하고,
  summary 는 ``logs/ingestion_report.json`` 에도 남긴다(CLI 와 동일).
"""
from __future__ import annotations

import json
import threading
import unicodedata
import uuid
from datetime import datetime
from pathlib import Path

from loguru import logger

from src.config import settings
from src.ingestion.pipeline import ingest_directory, ingest_paths


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


class JobConflictError(RuntimeError):
    """이미 적재 job 이 실행 중(동시 1개 정책)."""


class JobRegistry:
    """적재 job 의 in-memory 레지스트리 + 스레드 실행. app.state 싱글톤으로 보관."""

    def __init__(self) -> None:
        self._jobs: dict[str, dict] = {}
        self._lock = threading.Lock()
        self._active_id: str | None = None

    def start(self, root: str | None, recreate: bool, limit: int | None) -> dict:
        """새 적재 job 을 스레드로 시작하고 job 레코드를 반환. 진행 중이면 conflict."""
        with self._lock:
            if self._active_id is not None:
                raise JobConflictError(f"ingestion already running (job_id={self._active_id})")
            job_id = uuid.uuid4().hex[:12]
            job = {
                "job_id": job_id,
                "status": "running",
                # NFC 정규화: macOS 경로는 NFD(분해형)라 표시용 root 만 NFC 로(표시상 일관).
                "root": unicodedata.normalize("NFC", str(Path(root) if root else settings.raw_dir)),
                "recreate": recreate,
                "limit": limit,
                "started_at": _now(),
                "finished_at": None,
                "summary": None,
                "error": None,
            }
            self._jobs[job_id] = job
            self._active_id = job_id
        threading.Thread(target=self._run, args=(job_id,), daemon=True).start()
        return job

    def _run(self, job_id: str) -> None:
        job = self._jobs[job_id]
        root = Path(job["root"])
        try:
            logger.info(f"[ingest {job_id}] start root={root} recreate={job['recreate']} limit={job['limit']}")
            if job["limit"]:
                pdfs = sorted(root.rglob("*.pdf"))[: job["limit"]]
                summary = ingest_paths(pdfs, recreate=job["recreate"])
            else:
                summary = ingest_directory(root, recreate=job["recreate"])
            job["summary"] = summary
            job["status"] = "done"
            self._write_report(summary)
            logger.success(f"[ingest {job_id}] done: ok={summary['ok']} failed={summary['failed']} chunks={summary['chunks']}")
        except Exception as e:  # 어떤 실패든 job 상태로 남긴다(스레드가 조용히 죽지 않게)
            job["status"] = "failed"
            job["error"] = str(e)
            logger.error(f"[ingest {job_id}] FAILED: {e}")
        finally:
            job["finished_at"] = _now()
            with self._lock:
                self._active_id = None

    @staticmethod
    def _write_report(summary: dict) -> None:
        try:
            settings.logs_dir.mkdir(parents=True, exist_ok=True)
            (settings.logs_dir / "ingestion_report.json").write_text(
                json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
            )
        except Exception:  # 리포트 기록 실패가 적재 성공을 뒤집지 않게
            pass

    def get(self, job_id: str) -> dict | None:
        return self._jobs.get(job_id)

    def list(self) -> dict:
        jobs = sorted(self._jobs.values(), key=lambda j: j["started_at"], reverse=True)
        return {"active": self._active_id, "jobs": jobs}
