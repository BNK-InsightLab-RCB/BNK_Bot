"""Answer-quality check on the full RAG pipeline (read-only).

eval_retrieval.py 가 '검색'만 채점한다면, 이건 ``ChatService.answer`` 전체를 돌려
'생성된 답변'을 채점한다. 자가채점 베이스라인(질문+기대답을 우리가 라벨)이라
gold benchmark 가 아니라, 프롬프트·모델·청킹·적재를 바꿀 때 **회귀 확인용 게이트**다.

채점 지표(전부 결정론적):
  1) 정확도   — 답 가능 질문: 답변에 기대 키워드가 모두 포함되는가.
  2) 거부(양방향) — 답 가능인데 "모름"이면 실패(false refusal) / 무관 질문인데
     "모름" 아니면 실패(hallucination).
  3) 숫자 충실도 — 답변의 '숫자+단위'(이율%/금액원/기간개월·년 등)가 검색된 근거
     본문에 실제로 존재하는가(없으면 위반으로 보고; 휴리스틱 review 신호).
  4) 출처     — sources 개수.

실행: python scripts/eval_answer.py  (Qdrant + Ollama(qwen3.5-bnk) 가동 필요)
결과: logs/eval_answer.log / logs/eval_answer_report.json (덮어쓰기)
"""
from __future__ import annotations

import json
import re
import sys
import time
from datetime import datetime
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parent.parent))

from src.chat.generator import Generator  # noqa: E402
from src.chat.retriever import Retriever  # noqa: E402
from src.chat.schemas import QueryRequest  # noqa: E402
from src.chat.service import ChatService  # noqa: E402
from src.config import settings  # noqa: E402
from src.ingestion.embedder import Embedder  # noqa: E402
from src.ingestion.qdrant import QdrantStore  # noqa: E402

TOP_K = 5
REFUSAL_MARK = "확인되지 않습니다"  # service._NO_CONTEXT_ANSWER / SYSTEM_PROMPT 규칙

# 답 가능 질문: expect = 답변에 모두 포함돼야 하는 키워드(실제 근거에서 검증한 값).
# 무관 질문: refuse = True (예금 도메인 밖 → "모름"이 나와야 정상).
# 기타 상품(장병~RP)·도메인밖 거부(펀드/외환/보험)는 과적합 점검용 held-out 으로 만든 뒤
# 통과 확인하여 회귀 그물을 넓히려 표준셋에 편입(상품 커버리지 ↑). 다음 일반화 점검은 또
# 새 질문으로 한다(편입된 건 이제 "본 문제"라 신선한 held-out 가치는 없음).
QUESTIONS = [
    # -- 답 가능: 마이플랜 퇴직연금 --
    {"q": "마이플랜퇴직연금정기예금은 양도할 수 있나요?", "expect": ["불가"]},
    {"q": "마이플랜 퇴직연금 질권설정이 되나요?", "expect": ["불가"]},
    {"q": "이 퇴직연금은 비과세종합저축으로 가입할 수 있나요?", "expect": ["없"]},
    {"q": "마이플랜 퇴직연금 분할해지(분할인출) 가능한가요?", "expect": ["가능"]},
    {"q": "마이플랜 퇴직연금 예금자보호가 되나요?", "expect": ["보호"]},
    {"q": "마이플랜 퇴직연금정기예금 가입 대상이 누구야?", "expect": ["퇴직연금"]},
    {"q": "퇴직연금정기예금 6개월 미만 중도해지 적용비율은?", "expect": ["40"]},
    {"q": "퇴직연금정기예금 9개월 이상 11개월 미만 중도해지 적용비율은?", "expect": ["80"]},
    # -- 답 가능: 기타 상품(상품 커버리지 확장) --
    {"q": "장병내일준비적금 가입 대상이 누구야?", "expect": ["현역"]},
    {"q": "마이플랜ISA정기예금 6개월 미만 중도해지 적용비율은?", "expect": ["40"]},
    {"q": "회전플러스정기예금은 이자를 어떻게 지급해?", "expect": ["회전"]},
    {"q": "양도성예금증서(CD) 가입 대상에 제한이 있나요?", "expect": ["제한"]},
    {"q": "BNK내맘대로예금은 어떤 종류의 예금인가요?", "expect": ["정기예금"]},
    {"q": "환매조건부매도(RP)의 상품유형은?", "expect": ["거치"]},
    # -- 무관/도메인 밖 → 거부해야 정상 --
    {"q": "오늘 비트코인 시세 알려줘", "refuse": True},
    {"q": "주택담보대출 금리가 몇 퍼센트야?", "refuse": True},
    {"q": "신용카드 연회비는 얼마야?", "refuse": True},
    {"q": "펀드 수익률이 얼마나 돼?", "refuse": True},
    {"q": "오늘 달러 환율 알려줘", "refuse": True},
    {"q": "실손보험 보장 내용 알려줘", "refuse": True},
]

_NUM = r"\d[\d,]*(?:\.\d+)?"
_UNIT = r"%|퍼센트|원|개월|년|일|회|만원|억"
_NUMUNIT = re.compile(rf"({_NUM})\s*(?:{_UNIT})")


def _norm(n: str) -> str:
    return n.replace(",", "")


def number_violations(answer: str, source_text: str) -> list[str]:
    """답변의 '숫자+단위' 중 근거 본문에 없는 값을 반환(숫자 변조 후보)."""
    src = {_norm(d) for d in re.findall(_NUM, source_text)}
    return [m for m in _NUMUNIT.findall(answer) if _norm(m) not in src]


def grade(item: dict, answer: str) -> tuple[bool, str]:
    refused = REFUSAL_MARK in answer
    if item.get("refuse"):
        return refused, "거부-정상" if refused else "환각(거부해야 함)"
    if refused:
        return False, "FALSE 모름(답해야 함)"
    missing = [e for e in item["expect"] if e not in answer]
    return (not missing), ("정확" if not missing else f"기대 누락 {missing}")


def main() -> None:
    emb = Embedder()
    store = QdrantStore(
        url=settings.qdrant_url,
        collection=settings.qdrant_collection_name,
        dim=emb.dim,
        api_key=settings.qdrant_api_key,
    )
    retriever = Retriever(emb, store)
    service = ChatService(retriever, Generator())

    lines: list[str] = []

    def out(s: str = "") -> None:
        print(s)
        lines.append(s)

    out(f"# eval_answer @ {datetime.now().isoformat(timespec='seconds')}  model={settings.llm_model}")
    out(f"== ANSWER QUALITY (top-{TOP_K}, {len(QUESTIONS)} questions) ==")

    n_ans = sum(1 for it in QUESTIONS if not it.get("refuse"))
    n_ref = len(QUESTIONS) - n_ans
    correct = ans_correct = ref_correct = total_viol = 0
    records = []

    for i, item in enumerate(QUESTIONS, 1):
        q = item["q"]
        hits = retriever.retrieve(q, top_k=TOP_K)  # full bodies (숫자검증용)
        t = time.time()
        resp = service.answer(QueryRequest(question=q, top_k=TOP_K))
        dt = time.time() - t

        ok, why = grade(item, resp.answer)
        src_text = " ".join((h.payload.get("body", "") or "") for h in hits)
        viol = [] if item.get("refuse") else number_violations(resp.answer, src_text)
        correct += ok
        total_viol += len(viol)
        if item.get("refuse"):
            ref_correct += ok
        else:
            ans_correct += ok

        kind = "거부" if item.get("refuse") else "답변"
        out(f"{'✓' if ok else '✗'} [{i:2}] {kind} ({dt:4.1f}s) {why}"
            + (f"  ⚠숫자위반={viol}" if viol else "")
            + f"\n        Q: {q}\n        A: {resp.answer[:120].replace(chr(10), ' ')}")
        records.append({
            "q": q, "kind": kind, "correct": ok, "why": why,
            "answer": resp.answer, "number_violations": viol,
            "used_chunks": resp.used_chunks, "latency_s": round(dt, 1),
        })

    n = len(QUESTIONS)
    out("")
    out(f"정확도(전체)      = {correct}/{n} ({correct/n*100:.0f}%)")
    out(f"  답변 정확도     = {ans_correct}/{n_ans}")
    out(f"  거부 정확도     = {ref_correct}/{n_ref}")
    out(f"숫자 위반(총)     = {total_viol}  (답변 숫자가 근거에 없던 횟수; 0이 이상적)")

    settings.logs_dir.mkdir(parents=True, exist_ok=True)
    (settings.logs_dir / "eval_answer.log").write_text("\n".join(lines) + "\n", encoding="utf-8")
    (settings.logs_dir / "eval_answer_report.json").write_text(
        json.dumps({
            "timestamp": datetime.now().isoformat(timespec="seconds"),
            "model": settings.llm_model, "top_k": TOP_K, "questions": n,
            "correct": correct, "answer_correct": ans_correct, "refusal_correct": ref_correct,
            "answerable": n_ans, "refusable": n_ref, "number_violations": total_viol,
            "results": records,
        }, ensure_ascii=False, indent=2), encoding="utf-8")
    out(f"\nsaved -> {settings.logs_dir/'eval_answer.log'}")
    out(f"saved -> {settings.logs_dir/'eval_answer_report.json'}")


if __name__ == "__main__":
    main()
