"""검색 score 임계값 보정 측정 (read-only).

**왜 필요한가.** 지금 검색은 `limit=top_k` 만 걸려 있어 질문이 아무리 무관해도 Qdrant 가
항상 top-k 를 채워 준다. 실측상 eval_answer 의 '거부해야 정상' 6문항이 전부
``used_chunks=5`` 였다 — 즉 **"모름" 거부가 전적으로 LLM 협조에 의존**하고 있고,
`service` 의 검색 0건 즉시거부 경로는 한 번도 발동한 적이 없다.

임계값을 걸면 무관 질문을 LLM 이전에 결정론적으로 잘라낼 수 있다. 다만 임계값을
감으로 정하면 정상 답변까지 죽으므로(=false refusal), **두 분포를 먼저 재고 정한다.**

질문군 3종 (구분이 중요)
------------------------
- ``IN``      : 색인된 문서로 답할 수 있어야 하는 질문 → **높은 score 가 나와야 정상**
- ``OUT``     : 도메인 자체가 밖(날씨/시세/일상) → **낮아야 정상**. 영구적으로 거부 대상
- ``NOT_YET`` : 도메인은 맞지만 **아직 미적재**(펀드 등) → 지금은 거부가 정답이지만
                적재 후에는 IN 으로 바뀐다. 임계값을 이 그룹에 맞춰 잡으면 적재 후
                과차단이 되므로 **경계 계산에서 제외**하고 참고용으로만 본다.

실행:  python scripts/measure_score_threshold.py
결과:  logs/score_threshold.log / logs/score_threshold_report.json
"""
from __future__ import annotations

import json
import statistics as stat
import sys
from datetime import datetime
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parent.parent))

from src.chat.retriever import Retriever  # noqa: E402
from src.config import settings  # noqa: E402
from src.ingestion.embedder import Embedder  # noqa: E402
from src.ingestion.qdrant import QdrantStore  # noqa: E402

TOP_K = 5

IN = [
    "마이플랜퇴직연금정기예금은 양도할 수 있나요?",
    "마이플랜 퇴직연금 질권설정이 되나요?",
    "이 퇴직연금은 비과세종합저축으로 가입할 수 있나요?",
    "마이플랜 퇴직연금 분할해지(분할인출) 가능한가요?",
    "마이플랜 퇴직연금 예금자보호가 되나요?",
    "마이플랜 퇴직연금정기예금 가입 대상이 누구야?",
    "퇴직연금정기예금 6개월 미만 중도해지 적용비율은?",
    "퇴직연금정기예금 9개월 이상 11개월 미만 중도해지 적용비율은?",
    "장병내일준비적금 가입 대상이 누구야?",
    "마이플랜ISA정기예금 6개월 미만 중도해지 적용비율은?",
    "회전플러스정기예금은 이자를 어떻게 지급해?",
    "양도성예금증서(CD) 가입 대상에 제한이 있나요?",
    "BNK내맘대로예금은 어떤 종류의 예금인가요?",
    "환매조건부매도(RP)의 상품유형은?",
    # 임계 하한을 보수적으로 잡기 위한 '어려운 IN' — 짧거나 상품명이 없는 질문.
    "예금자보호 한도가 얼마야?",
    "중도해지하면 이자 손해 보나요?",
    "적금 자동이체 신청할 수 있어?",
    "만기일에 자동재예치 되나요?",
    "통장 분실하면 어떻게 해?",
    "저탄소실천예금 우대금리 조건은?",
]

OUT = [
    "오늘 비트코인 시세 알려줘",
    "오늘 달러 환율 알려줘",
    "내일 부산 날씨 어때?",
    "김치찌개 끓이는 법 알려줘",
    "파이썬으로 웹서버 만드는 법",
    "손흥민 어제 경기 결과",
    "회사 연차 며칠 남았는지 알려줘",
    "코스피 지수 얼마야?",
    "아이폰 최신 모델 가격",
    "부산에서 서울 KTX 시간표",
]

NOT_YET = [   # 도메인은 맞지만 아직 미적재 → 적재되면 IN 으로 바뀐다
    "펀드 수익률이 얼마나 돼?",
    "주택담보대출 금리가 몇 퍼센트야?",
    "신용카드 연회비는 얼마야?",
    "실손보험 보장 내용 알려줘",
]


def stats(xs: list[float]) -> dict:
    return {
        "n": len(xs),
        "min": round(min(xs), 4),
        "p25": round(sorted(xs)[len(xs) // 4], 4),
        "median": round(stat.median(xs), 4),
        "max": round(max(xs), 4),
    }


def main() -> None:
    emb = Embedder()
    store = QdrantStore(
        url=settings.qdrant_url,
        collection=settings.qdrant_collection_name,
        dim=emb.dim,
        api_key=settings.qdrant_api_key,
    )
    retriever = Retriever(emb, store)

    lines: list[str] = [
        f"# score threshold 보정 @ {datetime.now().isoformat(timespec='seconds')}",
        f"# collection points={store.count()} top_k={TOP_K}",
    ]
    groups = {"IN": IN, "OUT": OUT, "NOT_YET": NOT_YET}
    scores: dict[str, list[float]] = {}
    detail: dict[str, list[dict]] = {}

    for name, qs in groups.items():
        tops, rows = [], []
        for q in qs:
            # score_threshold=0.0 — **보정 도구는 임계의 영향을 받으면 안 된다**.
            # (기본값을 쓰면 OUT 이 전부 빈 결과가 되어 분포를 잴 수 없다.)
            hits = retriever.retrieve(q, top_k=TOP_K, score_threshold=0.0)
            top1 = hits[0].score if hits else 0.0
            tops.append(top1)
            rows.append({
                "q": q,
                "top1": round(top1, 4),
                "top1_product": hits[0].payload.get("product_name", "") if hits else "",
                "all": [round(h.score, 4) for h in hits],
            })
        scores[name] = tops
        detail[name] = rows

    lines.append("\n== 그룹별 top1 score 분포 ==")
    for name in groups:
        lines.append(f"  {name:<8} {stats(scores[name])}")

    # 경계: IN 의 최저점과 OUT 의 최고점 사이. NOT_YET 은 의도적으로 제외.
    in_min, out_max = min(scores["IN"]), max(scores["OUT"])
    gap = in_min - out_max
    lines.append("\n== 분리도 ==")
    lines.append(f"  IN.min  = {in_min:.4f}")
    lines.append(f"  OUT.max = {out_max:.4f}")
    lines.append(f"  gap     = {gap:+.4f}  ({'분리됨' if gap > 0 else '겹침 — 단일 임계로 불가'})")

    if gap > 0:
        # 중점을 쓰되 IN 쪽에 여유를 더 둔다(정상 답변을 죽이는 쪽이 더 나쁨).
        suggested = round(out_max + gap * 0.4, 3)
        lines.append(f"\n  → 권장 임계 = {suggested}  (OUT.max 위 40% 지점, IN 쪽 여유 확보)")
        lines.append(f"    이 값이면 IN {sum(s >= suggested for s in scores['IN'])}/{len(IN)} 통과, "
                     f"OUT {sum(s < suggested for s in scores['OUT'])}/{len(OUT)} 차단")
    else:
        lines.append("\n  → 단일 절대임계로는 분리 불가. top1-top5 격차/카테고리 일관성 등 다른 신호 필요.")

    lines.append("\n== NOT_YET(미적재 도메인) 참고 ==")
    lines.append("   적재되면 IN 이 되므로 임계 계산에서 제외했다. 현재 점수:")
    for r in detail["NOT_YET"]:
        lines.append(f"   {r['top1']:.4f}  {r['q']}")

    lines.append("\n== IN 하위 5개(임계에 가장 가까운 질문) ==")
    for r in sorted(detail["IN"], key=lambda r: r["top1"])[:5]:
        lines.append(f"   {r['top1']:.4f}  {r['q']}  → {r['top1_product']}")

    lines.append("\n== OUT 상위 5개(가장 높게 잡힌 무관 질문) ==")
    for r in sorted(detail["OUT"], key=lambda r: -r["top1"])[:5]:
        lines.append(f"   {r['top1']:.4f}  {r['q']}  → {r['top1_product']}")

    report = "\n".join(lines)
    print(report)

    settings.logs_dir.mkdir(parents=True, exist_ok=True)
    (settings.logs_dir / "score_threshold.log").write_text(report, encoding="utf-8")
    (settings.logs_dir / "score_threshold_report.json").write_text(
        json.dumps({
            "timestamp": datetime.now().isoformat(timespec="seconds"),
            "points": store.count(),
            "top_k": TOP_K,
            "stats": {k: stats(v) for k, v in scores.items()},
            "in_min": round(in_min, 4),
            "out_max": round(out_max, 4),
            "gap": round(gap, 4),
            "detail": detail,
        }, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
