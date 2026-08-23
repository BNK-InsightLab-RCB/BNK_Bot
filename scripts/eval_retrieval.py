"""Retrieval sanity/quality check on the loaded collection (read-only).

Two parts:
  1) INTEGRITY  — point count + metadata distribution (did the data land right?).
  2) RETRIEVAL  — a small hand-labelled question set; for each question check
     whether the top-k chunks satisfy the expectation (right product and/or a
     required keyword). Reports pass@1 / pass@5 and per-question detail.

This is a self-graded baseline (questions + expected answers written by us), so
treat it as a sanity gate before building the engine, not a gold benchmark.
"""
from __future__ import annotations

import json
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parent.parent))

from src.config import settings  # noqa: E402
from src.ingestion.embedder import Embedder  # noqa: E402
from src.ingestion.qdrant import QdrantStore  # noqa: E402

TOP_K = 5

# Each: question + (optional) product substring that must appear in a hit chunk's
# product_name, and (optional) keywords (ANY must appear in a hit chunk body).
QUESTIONS = [
    {"q": "마이플랜퇴직연금정기예금은 양도할 수 있나요?", "product": "마이플랜", "keywords": ["양도", "불가"]},
    {"q": "마이플랜 퇴직연금 질권설정이 되나요?", "product": "마이플랜", "keywords": ["질권설정"]},
    {"q": "퇴직연금정기예금 9개월 미만 중도해지 이율은?", "product": "마이플랜", "keywords": ["중도해지", "경과일수"]},
    {"q": "마이플랜 퇴직연금 기본이율 알려줘", "product": "마이플랜", "keywords": ["1.80", "기본이율"]},
    {"q": "이 퇴직연금은 비과세종합저축 가입이 되나요?", "product": "마이플랜", "keywords": ["비과세종합저축"]},
    {"q": "마이플랜 분할인출(분할해지) 가능한가요?", "product": "마이플랜", "keywords": ["분할"]},
    {"q": "퇴직연금 예금자보호 되나요?", "product": "마이플랜", "keywords": ["예금자보호"]},
    {"q": "마이플랜 퇴직연금 가입 대상이 누구야?", "product": "마이플랜", "keywords": ["퇴직연금", "가입대상"]},
    {"q": "장병내일준비적금 가입 대상은?", "product": "장병내일준비적금", "keywords": ["병역", "현역"]},
    {"q": "BNK내맘대로예금은 어떤 상품이야?", "product": "BNK내맘대로예금", "keywords": []},
    {"q": "환매조건부매도(RP) 상품 알려줘", "product": "환매조건부매도", "keywords": []},
    {"q": "회전플러스정기예금 특징?", "product": "회전플러스정기예금", "keywords": []},
    {"q": "양도성예금증서(CD) 상품 있어?", "product": "양도성예금증서", "keywords": []},
    {"q": "메리트정기예금 금리 조건?", "product": "메리트정기예금", "keywords": []},
    {"q": "청년 주택청약 통장 있나요?", "product": "청약", "keywords": []},
]


def judge(hits, product, keywords) -> bool:
    prod_ok = (not product) or any(product in (h.payload.get("product_name") or "") for h in hits)
    kw_ok = (not keywords) or any(
        any(kw in (h.payload.get("body") or "") for kw in keywords) for h in hits
    )
    return prod_ok and kw_ok


def main() -> None:
    store = QdrantStore(
        url=settings.qdrant_url,
        collection=settings.qdrant_collection_name,
        api_key=settings.qdrant_api_key,
    )
    lines: list[str] = []

    def out(s: str = "") -> None:  # print + capture for the log file
        print(s)
        lines.append(s)

    # 1) integrity
    cat, dt, prods = Counter(), Counter(), set()
    nxt = None
    while True:
        pts, nxt = store.client.scroll(store.collection, limit=500, offset=nxt, with_payload=True)
        for p in pts:
            cat[p.payload["category"]] += 1
            dt[p.payload["doc_type"]] += 1
            prods.add(p.payload["product_name"])
        if nxt is None:
            break
    out(f"# eval_retrieval @ {datetime.now().isoformat(timespec='seconds')}")
    out("== INTEGRITY ==")
    out(f"points={store.count()}  products={len(prods)}  category={dict(cat)}  doc_type={dict(dt)}\n")

    # 2) retrieval
    emb = Embedder()
    pass1 = pass5 = 0
    records = []
    out(f"== RETRIEVAL (top-{TOP_K}) ==")
    for i, item in enumerate(QUESTIONS, 1):
        hits = store.search(emb.embed_query(item["q"]), top_k=TOP_K)
        ok5 = judge(hits, item.get("product"), item.get("keywords"))
        ok1 = judge(hits[:1], item.get("product"), item.get("keywords"))
        pass1 += ok1
        pass5 += ok5
        top = hits[0].payload
        out(f"{'✓' if ok5 else '✗'} [{i:2}] @1={'O' if ok1 else 'X'} @5={'O' if ok5 else 'X'}  "
            f"top1=({top['product_name'][:16]}|{hits[0].score:.2f}) :: {item['q']}")
        records.append({"q": item["q"], "pass@1": ok1, "pass@5": ok5,
                        "top1_product": top["product_name"], "top1_score": round(hits[0].score, 3)})
    n = len(QUESTIONS)
    out(f"\npass@1 = {pass1}/{n} ({pass1/n*100:.0f}%)   pass@5 = {pass5}/{n} ({pass5/n*100:.0f}%)")

    # persist results
    settings.logs_dir.mkdir(parents=True, exist_ok=True)
    (settings.logs_dir / "eval_retrieval.log").write_text("\n".join(lines) + "\n", encoding="utf-8")
    (settings.logs_dir / "eval_retrieval_report.json").write_text(
        json.dumps({
            "timestamp": datetime.now().isoformat(timespec="seconds"),
            "points": store.count(), "products": len(prods),
            "questions": n, "pass@1": pass1, "pass@5": pass5,
            "pass@1_rate": round(pass1 / n, 3), "pass@5_rate": round(pass5 / n, 3),
            "results": records,
        }, ensure_ascii=False, indent=2), encoding="utf-8")
    out(f"\nsaved -> {settings.logs_dir/'eval_retrieval.log'}")
    out(f"saved -> {settings.logs_dir/'eval_retrieval_report.json'}")


if __name__ == "__main__":
    main()
