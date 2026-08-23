"""장애 경로 검증 — 의존성이 죽었을 때 엔진이 '어떻게' 죽는지 실측한다.

납품 시스템에서 중요한 건 "안 죽는다"가 아니라 **죽는 방식이 예측 가능한가**다.
LLM 이 내려가면 raw 500 스택이 고객에게 나가면 안 되고, Qdrant 가 내려가면
readiness 가 정직하게 실패해서 로드밸런서가 트래픽을 빼야 한다.

무거운 모델(KURE)을 띄우지 않도록 **의존성을 스텁으로 주입**한다 — 여기서 보려는 건
검색 품질이 아니라 예외→HTTP 매핑이라서. (Qdrant 항목만 실제 죽은 포트를 쓴다.)

실행:  python scripts/check_failure_paths.py     (종료코드 0 = 전부 통과)
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parent.parent))

from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from src.chat.audit import audit_path  # noqa: E402
from src.chat.generator import Generator  # noqa: E402
from src.chat.router import router as chat_router  # noqa: E402
from src.chat.service import ChatService  # noqa: E402
from src.config import settings  # noqa: E402
from src.ingestion.qdrant import QdrantStore  # noqa: E402
from src.main import health  # noqa: E402

results: list[tuple[bool, str]] = []


def ok(cond: bool, label: str, detail: str = "") -> None:
    results.append((cond, f"{'PASS' if cond else 'FAIL'}  {label}" + (f"  ({detail})" if detail else "")))


class _Hit:
    """검색 결과 스텁(ScoredPoint 대역)."""

    def __init__(self, score: float = 0.9):
        self.score = score
        self.payload = {
            "product_name": "테스트예금", "doc_type": "설명서", "page": 1,
            "section": "거래조건", "body": "| 중도해지 | 기본이율 x 40% |",
            "source_file": "test.pdf", "chunk_index": 0,
        }


class _StubRetriever:
    def __init__(self, hits):
        self.hits = hits
        self.store = None

    def retrieve(self, *a, **kw):
        return self.hits


def _client(retriever, generator) -> TestClient:
    app = FastAPI()
    app.include_router(chat_router)
    app.state.chat_service = ChatService(retriever, generator)
    return TestClient(app, raise_server_exceptions=False)


def main() -> None:
    # ── 1) LLM 다운 → 503 (raw 500 스택 노출 금지) ──────────────────────────
    dead_llm = Generator()
    dead_llm.client = Generator().client.__class__(
        base_url="http://127.0.0.1:1/v1", api_key="x", timeout=2.0
    )
    r = _client(_StubRetriever([_Hit()]), dead_llm).post("/query", json={"question": "중도해지 이율은?"})
    ok(r.status_code == 503, "LLM 다운 → 503", f"got {r.status_code}")
    ok("답변 생성" in r.text or "일시적" in r.text, "503 본문이 고객용 안내문", r.text[:60])
    ok("Traceback" not in r.text, "스택 트레이스 미노출")

    # ── 2) 검색 0건(임계 미달) → LLM 호출 없이 즉시 거부 ────────────────────
    r = _client(_StubRetriever([]), dead_llm).post("/query", json={"question": "오늘 날씨"})
    ok(r.status_code == 200, "근거 0건 → 200", f"got {r.status_code}")
    body = r.json()
    ok(body["used_chunks"] == 0 and "확인되지 않습니다" in body["answer"],
       "근거 0건 → LLM 미호출 거부(LLM 이 죽어 있어도 성공)")

    # ── 3) Qdrant 다운 → /health 503 (readiness 정직) ───────────────────────
    class _Req:
        class app:
            class state:
                pass
    _Req.app.state.retriever = type("R", (), {
        "store": QdrantStore(url="http://127.0.0.1:1", collection="x", dim=1024)
    })()
    try:
        health(_Req)  # type: ignore[arg-type]
        ok(False, "Qdrant 다운 → /health 503", "예외가 발생하지 않음")
    except Exception as e:
        ok(getattr(e, "status_code", None) == 503, "Qdrant 다운 → /health 503", type(e).__name__)

    # ── 4) 감사 로그가 실제로 쌓였는가 ──────────────────────────────────────
    p = audit_path()
    ok(p.exists(), "감사 로그 파일 생성", str(p))
    if p.exists():
        last = [l for l in p.read_text(encoding="utf-8").splitlines() if l.strip()][-1]
        ev = json.loads(last)
        need = {"ts", "question", "answer", "refused", "grounded", "violations", "evidence", "latency_s"}
        ok(need <= set(ev), "감사 이벤트 필수 필드", f"missing={sorted(need - set(ev))}")

    # ── 5) job 이력 파일 복원(재시작 내성) ──────────────────────────────────
    from src.ingestion.jobs import JobRegistry
    jf = settings.logs_dir / JobRegistry.JOBS_FILE
    reg = JobRegistry()          # 파일이 있으면 복원, 없으면 빈 상태
    ok(isinstance(reg.list(), dict), "JobRegistry 복원 동작", f"jobs={len(reg.list()['jobs'])}")
    ok(reg.list()["active"] is None, "복원 시 active 잠금 없음(중단 job 은 interrupted)")
    if jf.exists():
        ok(all(j["status"] != "running" for j in reg.list()["jobs"]),
           "이전 프로세스의 running → interrupted 로 표시")

    print("\n".join(m for _, m in results))
    passed = sum(c for c, _ in results)
    print(f"\n== {passed}/{len(results)} passed ==")
    sys.exit(0 if passed == len(results) else 1)


if __name__ == "__main__":
    main()
