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

    # ── 2026-09-05 추가: 코퍼스가 예금 2카테고리 → 9카테고리(234,050청크)로 바뀌었다.
    # 위 20문항은 전부 예금이라, 그것만으로 잡은 임계는 펀드·보험·신탁 질문에 대해
    # 검증된 바가 없다. 아래는 **실제 색인된 상품명을 Qdrant 페이로드에서 뽑아** 만들고
    # 검색이 해당 도메인 문서를 찾는지 1건씩 확인한 것들이다(전부 0.61 이상).
    "AB글로벌고수익증권투자신탁의 투자위험등급은?",
    "펀드 환매수수료는 어떻게 되나요?",
    "집합투자업자와 판매회사는 어떻게 다른가요?",
    "삼성달러표시단기채권증권자투자신탁 환헤지를 하나요?",
    "경남지역개발 신탁의 신탁기간이 얼마인가요?",
    "특정금전신탁 중도해지가 가능한가요?",
    "외화정기예금 가입 통화는 어떤 게 있나요?",
    "꿈이룸외화자유적금 가입금액 제한이 있나요?",
    "주택담보노후연금대출 상환 방법은?",
    "가계대출 중도상환수수료가 있나요?",
    "전자금융서비스 이체한도는 얼마인가요?",
    "신용카드 분실하면 어떻게 신고하나요?",
    "다모아상해보험 보험료 납입기간은?",
    "변액보험 최저보증이 무엇인가요?",
    "변액저축보험 특별계정 운용 실적은 어떻게 확인하나요?",
    "금융주소 한번에 서비스가 무엇인가요?",
    "가족사랑통장 우대 혜택이 뭐야?",
    "주택청약예금 가입 자격은?",
]
# ⚠️ IN 의 의미: "**게이트가 열려야 한다**"이지 "top1 이 정확히 그 상품이다"가 아니다.
# top1 정확도는 `eval_retrieval.py`(pass@1/@5)가 따로 잰다. 실제로 위 질문 중 몇 개는
# 같은 도메인의 인접 상품을 top1 으로 물어온다(예: 주택청약예금 → 주택청약부금).

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

NOT_YET = [   # 도메인은 맞지만 근거가 색인에 없다 → 지금은 "모름"이 정답
    # 2026-09-05 갱신: 펀드·대출·카드는 적재됐으므로 IN 으로 옮겼다.
    # 남은 것은 **근거가 실제로 없음을 청크 단위로 확인한** 질문들이다.
    "실손보험 보장 내용 알려줘",          # 보험/약관 642건 중 27건(4%)만 색인
    "그린카드 연회비는 얼마인가요?",       # 그린카드 5청크 중 '연회비' 포함 0개 — 카드 표 추출 실패
    "공동인증서 재발급은 어떻게 하나요?",   # 공동인증 문서가 1청크뿐이고 '재발급' 언급 없음
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
            # use_lexical=False: 임계가 관장하는 것은 **게이트(무필터 dense)** 다.
            # 어휘 필터를 켠 채로 재면 좁혀진 집합의 top1 을 재게 되어(실측 IN.min
            # 0.6245 → 0.4664) 게이트가 실제로 하는 일과 다른 값을 잡는다.
            hits = retriever.retrieve(q, top_k=TOP_K, score_threshold=0.0,
                                      use_lexical=False)
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

    # ── 임계 스윕.
    # 예전엔 gap<=0 이면 "분리 불가"로 끝냈는데, 그 판정은 **완전 분리만 성공으로 치는**
    # 이분법이라 실제 최적 운영점을 놓친다. 코퍼스가 234,050청크로 커지자 무관 질문도
    # 어딘가에 0.67 로 걸리게 됐고(예: "코스피 지수" → 펀드 투자설명서), 완전 분리는
    # 원리상 불가능해졌다. 그래서 **IN 무손실을 제약으로 두고 OUT 차단을 최대화**한다.
    #   왜 IN 무손실이 제약인가: 정상 질문을 죽이는 false refusal 이 무관 질문을 통과시키는
    #   것보다 훨씬 나쁘다. 통과한 무관 질문은 뒤의 LLM 프롬프트+숫자 가드레일이 한 번 더
    #   거른다(2단 방어). 반대로 게이트에서 죽은 정상 질문은 복구 경로가 없다.
    # 0.005 격자에서 직접 고른다. **사후에 안전여유를 빼지 않는다** — 빼면 보고한 수치와
    # 권장값이 어긋난다(실제로 그 버그가 있었다: 0.600 에서 잰 'OUT 9/10'을 0.595 권장에
    # 붙였는데, 0.595 에서는 달러환율 0.5972 가 통과해 8/10 이었다).
    # 여유는 격자에서 자연히 확보된다(권장값과 IN.min 의 거리로 보고).
    grid = [round(0.40 + 0.005 * i, 3) for i in range(81)]
    lines.append("\n== 임계 스윕 (IN 무손실 구간만) ==")
    lines.append(f"  {'임계':>7} | {'IN 통과':>12} | {'OUT 차단':>12}")
    best = None
    for t in grid:
        ip = sum(s >= t for s in scores["IN"])
        ob = sum(s < t for s in scores["OUT"])
        if ip == len(IN):
            # 동점이면 **낮은 쪽**을 택한다: OUT 차단 성능이 같다면 IN 여유가 큰 쪽이 안전.
            if best is None or ob > best[2]:
                best = (t, ip, ob)
            lines.append(f"  {t:>7.3f} | {ip:>3}/{len(IN)} {100*ip//len(IN):>3}% | "
                         f"{ob:>3}/{len(OUT)} {100*ob//len(OUT):>3}%")

    if best:
        t, ip, ob = best
        lines.append(f"\n  → 권장 임계 = {t}")
        lines.append(f"    IN {ip}/{len(IN)} 통과(무손실) · OUT {ob}/{len(OUT)} 차단")
        lines.append(f"    IN.min({in_min:.4f}) 까지 여유 {in_min - t:+.4f}")
        cur = settings.retrieval_score_threshold
        lines.append(f"    현재 설정값 = {cur} → IN {sum(s >= cur for s in scores['IN'])}/{len(IN)} 통과 · "
                     f"OUT {sum(s < cur for s in scores['OUT'])}/{len(OUT)} 차단")
        if ob < len(OUT):
            lines.append("    통과하는 무관 질문(LLM 프롬프트+숫자 가드레일이 2차로 거름):")
            for r in sorted((r for r in detail["OUT"] if r["top1"] >= t), key=lambda r: -r["top1"]):
                lines.append(f"      {r['top1']:.4f}  {r['q']}  → {r['top1_product']}")
    else:
        lines.append("\n  → IN 무손실 지점이 없다. 임계 단독으로는 불가 — 다른 신호 필요.")

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
