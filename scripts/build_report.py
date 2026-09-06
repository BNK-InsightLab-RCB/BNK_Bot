"""제출용 문서 생성 — `logs/full_eval.jsonl` 을 읽어 마크다운 3종을 만든다.

원본(JSONL)에는 문항별 질문·답변·근거·응답시간이 모두 들어 있으므로, 집계 기준을
바꾸고 싶으면 **재실행 없이 이 스크립트만 다시 돌리면 된다**(4.6시간짜리 평가를
다시 돌릴 일이 없도록 그렇게 설계했다).

출력:
  docs/테스트_결과서.md   집계·시나리오·한계 (본문)
  docs/테스트_문답집.md   914문항 전체, 카테고리별 (부록)

⚠️ **모범답안을 창작하지 않는다.** 이 평가셋의 정답은 "어느 상품 문서를 찾아야 하는가"
이지 답변 텍스트가 아니다. 문답집의 '정답 문서' 칸에는 gold 상품명과 **문서 원문 발췌**만
넣는다. 답변 내용의 정오 판정은 사람이 라벨한 33문항(`eval_answer.py`)에서만 한다.

⚠️ **거부 사유는 자동 분류하지 않는다.** 시도했으나 육안 판정과 크게 어긋났다
(자동 '결함 67%' vs 육안 '결함 7%'). 기계로 낼 수 있는 것(정답 문서를 찾았는가)만
자동으로 내고, 나머지는 표본 육안 확인 결과를 결과서에 서술한다.
"""
from __future__ import annotations

import json
import statistics as st
import sys
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parent.parent))

from qdrant_client import models as m  # noqa: E402

from src.config import settings  # noqa: E402
from src.ingestion.qdrant import QdrantStore  # noqa: E402

SRC = Path("logs/full_eval.jsonl")
OUTDIR = Path("docs")
CATS = ["예금", "펀드", "보험", "신탁", "대출", "카드", "외환", "전자금융", "기타"]


def pct(a: int, b: int) -> str:
    return f"{a}/{b} ({100*a//b}%)" if b else "-"


def load() -> list[dict]:
    return [json.loads(l) for l in SRC.read_text(encoding="utf-8").splitlines() if l.strip()]


def doc_types(rows) -> dict[str, str]:
    """gold 상품이 어떤 종류의 문서인지(설명서/약관) — 집계를 나누는 기준."""
    store = QdrantStore(url=settings.qdrant_url,
                        collection=settings.qdrant_collection_name,
                        api_key=settings.qdrant_api_key)
    out: dict[str, str] = {}
    for pn in {r["gold_product"] for r in rows}:
        pts, _ = store.client.scroll(
            store.collection, limit=1, with_payload=True,
            scroll_filter=m.Filter(must=[m.FieldCondition(
                key="product_name", match=m.MatchValue(value=pn))]))
        out[pn] = (pts[0].payload.get("doc_type") if pts else "?") or "?"
    return out


def table(rows: list[dict], label: str) -> list[str]:
    """카테고리별 집계표 한 벌."""
    by = defaultdict(list)
    for r in rows:
        by[r["category"]].append(r)
    out = [f"| 카테고리 | 문항 | 검색 top1 | 검색 top5 | 답변율 | 응답시간(중앙) | 숫자위반 |",
           "|---|---|---|---|---|---|---|"]
    for c in CATS:
        g = by.get(c, [])
        if not g:
            continue
        lat = [r["latency_s"] for r in g]
        out.append(
            f"| {c} | {len(g)} | {pct(sum(r['hit1'] for r in g), len(g))} "
            f"| {pct(sum(r['hit5'] for r in g), len(g))} "
            f"| {pct(sum(not r['refused'] for r in g), len(g))} "
            f"| {st.median(lat):.1f}초 | {sum(len(r['violations']) for r in g)} |")
    lat = [r["latency_s"] for r in rows]
    out.append(
        f"| **{label}** | **{len(rows)}** "
        f"| **{pct(sum(r['hit1'] for r in rows), len(rows))}** "
        f"| **{pct(sum(r['hit5'] for r in rows), len(rows))}** "
        f"| **{pct(sum(not r['refused'] for r in rows), len(rows))}** "
        f"| **{st.median(lat):.1f}초** | **{sum(len(r['violations']) for r in rows)}** |")
    return out


def esc(s: str) -> str:
    """마크다운 표/본문이 깨지지 않도록 최소 이스케이프."""
    return (s or "").replace("|", "\\|").replace("\n", " ").strip()


def build_qa(rows: list[dict], dt: dict[str, str]) -> str:
    """문답집 — 카테고리별 섹션, 문항마다 질문/정답문서/원문/답변/근거/응답시간."""
    L = [f"# BNK_Bot 테스트 문답집", "",
         f"생성일 {date.today()} · 전 {len(rows)}문항 · 엔진 응답 원문 그대로", "",
         "> **‘정답 문서’ 칸은 모범답안이 아니다.** 이 평가의 정답은 *어느 문서를 찾아야",
         "> 하는가*이며, 답변 문장의 정답은 별도로 라벨하지 않았다. 대조할 수 있도록",
         "> **문서 원문을 그대로** 실었다.", "", "---", ""]
    by = defaultdict(list)
    for r in rows:
        by[r["category"]].append(r)

    L += ["## 목차", ""]
    for c in CATS:
        if by.get(c):
            L.append(f"- [{c} ({len(by[c])}문항)](#{c})")
    L += ["", "---", ""]

    for c in CATS:
        g = by.get(c)
        if not g:
            continue
        L += [f"## {c}", "", f"{len(g)}문항 · 검색 top1 {pct(sum(r['hit1'] for r in g), len(g))}"
              f" · 중앙 응답 {st.median([r['latency_s'] for r in g]):.1f}초", ""]
        for i, r in enumerate(sorted(g, key=lambda x: x["q"]), 1):
            ok = "적중" if r["hit1"] else ("top5 적중" if r["hit5"] else "미적중")
            L += [f"### [{c}-{i:03d}] {esc(r['q'])}", "",
                  f"| 항목 | 내용 |", "|---|---|",
                  f"| 정답 문서 | {esc(r['gold_product'])} ({r['gold_doc_chars']:,}자) |",
                  f"| 챗봇 답변 | {esc(r['answer'])[:400]} |",
                  f"| 검색 | {ok} · 근거 {len(r['sources'])}건 |",
                  f"| 응답시간 | {r['latency_s']}초 |",
                  f"| 숫자검증 | {'위반 ' + str(len(r['violations'])) + '건' if r['violations'] else '통과'} |",
                  f"| 문서종류 | {dt.get(r['gold_product'], '?')} |", ""]
            ex = esc(r["gold_excerpt"])[:300]
            if ex:
                L += ["**정답 문서 원문(발췌)**", "", "```", ex, "```", ""]
            if r["sources"]:
                L += ["**챗봇이 근거로 삼은 문서**", "",
                      "| # | 파일 | 쪽 | 점수 | 발췌 |", "|---|---|---|---|---|"]
                for j, s in enumerate(r["sources"], 1):
                    L.append(f"| {j} | {esc(s['source_file'])[:60]} | {s['page']} "
                             f"| {s['score']:.3f} | {esc(s['snippet'])[:110]} |")
                L.append("")
            L.append("---")
            L.append("")
    return "\n".join(L)


def main() -> None:
    rows = load()
    OUTDIR.mkdir(exist_ok=True)
    dt = doc_types(rows)
    desc = [r for r in rows if dt.get(r["gold_product"]) == "설명서"]

    lat = [r["latency_s"] for r in rows]
    summary = {
        "n": len(rows),
        "hit1": sum(r["hit1"] for r in rows), "hit5": sum(r["hit5"] for r in rows),
        "answered": sum(not r["refused"] for r in rows),
        "refused": sum(r["refused"] for r in rows),
        "ref_miss": sum(1 for r in rows if r["refused"] and not r["hit5"]),
        "ref_found": sum(1 for r in rows if r["refused"] and r["hit5"]),
        "viol": sum(len(r["violations"]) for r in rows),
        "err": sum(1 for r in rows if r["error"]),
        "lat_med": st.median(lat), "lat_avg": sum(lat) / len(lat), "lat_max": max(lat),
        "lat_p90": sorted(lat)[int(len(lat) * 0.9)],
    }
    (OUTDIR / "_summary.json").write_text(
        json.dumps({"summary": summary,
                    "by_doc_type": dict(Counter(dt.get(r["gold_product"], "?") for r in rows)),
                    "table_all": table(rows, "전체"),
                    "table_desc": table(desc, "설명서만")},
                   ensure_ascii=False, indent=2), encoding="utf-8")
    (OUTDIR / "테스트_문답집.md").write_text(build_qa(rows, dt), encoding="utf-8")
    print(f"문답집 → {OUTDIR/'테스트_문답집.md'}")
    print(f"집계   → {OUTDIR/'_summary.json'}")
    for k, v in summary.items():
        print(f"  {k:<10} {v}")


if __name__ == "__main__":
    main()
