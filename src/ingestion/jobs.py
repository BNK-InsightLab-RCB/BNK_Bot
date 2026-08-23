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
from src.ingestion.pipeline import find_documents, ingest_directory, ingest_paths


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


class JobConflictError(RuntimeError):
    """이미 적재 job 이 실행 중(동시 1개 정책)."""


class IngestRootError(ValueError):
    """요청 root 가 허용 경계(``settings.data_root``) 밖이거나 디렉토리가 아님."""


def resolve_ingest_root(root: str | None) -> Path:
    """요청 root 를 검증해 실제 경로로. **임의 경로 스캔 차단**이 목적.

    적재 API 는 인증이 없으므로(인증 방식은 납품처 규격 종속) 최소한 경로만은
    ``settings.data_root`` 아래로 가둔다. 안 그러면 서버가 읽을 수 있는 아무
    디렉토리나 rglob 하게 된다.

    macOS 경로는 NFD(분해형)라 NFC 로 맞춰 비교한다 — 겉보기 같은 한글이
    코드포인트가 달라 경계 검사를 우회하는 일이 없도록.
    """
    def _n(p: Path) -> str:
        return unicodedata.normalize("NFC", str(p))

    base = settings.data_root.resolve()
    if root is None:
        # 기본 경로도 반드시 검사한다. 예전엔 그냥 반환해서, `DATA_ROOT` 가 잘못 설정되면
        # **적재가 0건으로 '성공'** 하고 끝났다(경계 검사는 통과, find_documents 는 빈 목록).
        # 조용한 실패라 운영자가 원인을 찾을 수 없다 → 여기서 즉시 거부한다.
        if not base.is_dir():
            raise IngestRootError(
                f"원본 문서 루트가 없습니다: {base}  "
                f"(.env 의 DATA_ROOT 를 실제 문서 위치로 지정하세요 — README 참조)"
            )
        return base
    p = Path(root).expanduser().resolve()
    base_s, p_s = _n(base), _n(p)
    if p_s != base_s and not p_s.startswith(base_s + "/"):
        raise IngestRootError(f"root must be inside {base_s}: {root}")
    if not p.is_dir():
        raise IngestRootError(f"not a directory: {root}")
    return p


class JobRegistry:
    """적재 job 의 in-memory 레지스트리 + 스레드 실행. app.state 싱글톤으로 보관."""

    #: 재시작 후에도 적재 이력을 볼 수 있도록 남기는 파일(내부 운영용 포맷).
    JOBS_FILE = "ingest_jobs.jsonl"

    def __init__(self) -> None:
        self._jobs: dict[str, dict] = {}
        self._lock = threading.Lock()
        self._active_id: str | None = None
        self._load()

    # ----- persistence --------------------------------------------------------
    def _path(self) -> Path:
        return settings.logs_dir / self.JOBS_FILE

    def _load(self) -> None:
        """이전 프로세스의 job 이력을 복원.

        기록이 in-memory 뿐이면 재시작 즉시 "언제 무엇을 적재했는가"가 사라진다.
        운영에서는 그게 곧 감사 불가라 파일로도 남긴다.

        ⚠️ 파일에 ``running`` 으로 남은 job 은 **프로세스가 죽어 중단된 것**이다
        (살아있는 스레드는 이 프로세스에 없다) → ``interrupted`` 로 표시한다.
        그대로 running 으로 두면 동시성 락이 영구히 잠긴 것처럼 보인다.
        """
        p = self._path()
        if not p.exists():
            return
        try:
            for line in p.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                job = json.loads(line)
                if job.get("status") == "running":
                    job["status"] = "interrupted"
                    job["error"] = "프로세스 재시작으로 중단됨(이력 복원 시 표시)"
                self._jobs[job["job_id"]] = job  # 같은 id 는 나중 기록이 이김
        except Exception as e:
            logger.warning(f"job 이력 복원 실패(무시하고 계속): {e}")

    def _persist(self, job: dict) -> None:
        try:
            settings.logs_dir.mkdir(parents=True, exist_ok=True)
            with self._path().open("a", encoding="utf-8") as f:
                f.write(json.dumps(job, ensure_ascii=False) + "\n")
        except Exception as e:  # 이력 기록 실패가 적재를 뒤집지 않게
            logger.warning(f"job 이력 기록 실패(무시): {e}")

    def start(self, root: str | None, limit: int | None) -> dict:
        """새 적재 job 을 스레드로 시작하고 job 레코드를 반환.

        진행 중이면 ``JobConflictError``, root 가 경계 밖이면 ``IngestRootError``.
        경로 검증은 **락 밖·스레드 시작 전**에 해서 잘못된 요청이 동기적으로 400 이
        되게 한다(job 을 만들어놓고 실패시키지 않는다).

        ``recreate`` 는 받지 않는다 — 컬렉션 삭제는 CLI 전용(schemas 주석 참조).
        """
        resolved = resolve_ingest_root(root)
        with self._lock:
            if self._active_id is not None:
                raise JobConflictError(f"ingestion already running (job_id={self._active_id})")
            job_id = uuid.uuid4().hex[:12]
            job = {
                "job_id": job_id,
                "status": "running",
                # NFC 정규화: macOS 경로는 NFD(분해형)라 표시용 root 만 NFC 로(표시상 일관).
                "root": unicodedata.normalize("NFC", str(resolved)),
                "recreate": False,  # API 경로에서는 항상 False (응답 스키마 호환용 필드)
                "limit": limit,
                "started_at": _now(),
                "finished_at": None,
                "summary": None,
                "error": None,
            }
            self._jobs[job_id] = job
            self._active_id = job_id
        self._persist(job)
        threading.Thread(target=self._run, args=(job_id,), daemon=True).start()
        return job

    def _run(self, job_id: str) -> None:
        job = self._jobs[job_id]
        root = Path(job["root"])
        try:
            logger.info(f"[ingest {job_id}] start root={root} recreate={job['recreate']} limit={job['limit']}")
            if job["limit"]:
                docs = find_documents(root)[: job["limit"]]
                summary = ingest_paths(docs, recreate=job["recreate"])
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
            self._persist(job)  # 종료 상태를 이력에 확정 기록
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
