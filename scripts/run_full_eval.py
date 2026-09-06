"""제출용 전량 평가 — 914문항을 **운영 엔진 그대로** 통과시켜 문항별로 기록한다.

기존 평가와의 차이:
  - `eval_retrieval_v2.py` : 검색만(LLM 미호출). 빠르지만 응답시간·거부·답변이 없다.
  - `eval_answer.py`       : 답변까지 보지만 33문항 자가채점이고 카테고리 구분이 없다.
  - 이 스크립트            : **전 문항 × 전체 파이프라인**. 문항별 원본을 JSONL 로 남겨
                            결과서와 문답집을 나중에 재조립할 수 있게 한다.

⚠️ **모범답안을 창작하지 않는다.** 이 평가셋의 gold 는 "어느 상품 문서를 찾아야 하는가"이지
답변 텍스트가 아니다. 그래서 정답 칸에는 **gold 상품명 + 그 문서의 실제 원문 발췌**만 넣는다.
답변 내용의 정오는 사람이 라벨한 33문항(`eval_answer.py`)에서만 판정한다.

거부를 **사유별로 나눠 기록한다** — 뭉뚱그리면 "거부율 30%"만 남아 오해를 산다:
  retrieval_miss : 정답 문서를 못 찾음            → 검색 결함
  empty_source   : 찾았으나 문서 내용이 사실상 없음 → 데이터 한계(카드 안내장 등)
  false_refusal  : 찾았고 내용도 있는데 거부      → 진짜 결함

중단되어도 이어서 돌 수 있다(JSONL 을 이어 쓰고, 이미 끝난 문항은 건너뛴다).

실행:  python scripts/run_full_eval.py            (엔진이 :8000 에 떠 있어야 함)
출력:  logs/full_eval.jsonl
"""
from __future__ import annotations

import json
import sys
import time
import unicodedata
import urllib.error
import urllib.request
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parent.parent))

from qdrant_client import models as m  # noqa: E402

from src.config import settings  # noqa: E402
from src.ingestion.qdrant import QdrantStore  # noqa: E402

ENGINE = "http://localhost:8000/query"
TOP_K = 5
OUT = Path("logs/full_eval.jsonl")
REFUSAL_MARK = "확인되지 않습니다"
EMPTY_DOC_CHARS = 500      # 상품 전체 본문이 이보다 짧으면 '내용 없음'으로 본다


def norm(s: str) -> str:
    return unicodedata.normalize("NFC", str(s or ""))


def loose(s: str) -> str:
    """상품명 비교용 — 띄어쓰기·부호 무시.

    이걸 안 하면 같은 문서를 오답으로 센다("계좌통합관리서비스이용" vs "… 이용").
    """
    import re
    return re.sub(r"[\s\-_·.,()\[\]{}/]+", "", norm(s))


def main() -> None:
    items = json.loads(Path("eval/eval_set.json").read_text(encoding="utf-8"))["items"]
    OUT.parent.mkdir(parents=True, exist_ok=True)
    done = set()
    if OUT.exists():
        for line in OUT.read_text(encoding="utf-8").splitlines():
            try:
                done.add(json.loads(line)["q"])
            except Exception:
                pass
        print(f"이어서 진행 — 이미 완료 {len(done)}문항")

    store = QdrantStore(url=settings.qdrant_url,
                        collection=settings.qdrant_collection_name,
                        api_key=settings.qdrant_api_key)
    doc_cache: dict[str, tuple[int, str]] = {}

    def gold_doc(product: str) -> tuple[int, str]:
        """gold 상품의 (총 글자수, 원문 발췌). 모범답안 칸의 근거로 쓴다."""
        if product not in doc_cache:
            pts, _ = store.client.scroll(
                store.collection, limit=60, with_payload=True,
                scroll_filter=m.Filter(must=[m.FieldCondition(
                    key="product_name", match=m.MatchValue(value=product))]))
            bodies = [norm(p.payload.get("body")) for p in pts]
            total = sum(len(b) for b in bodies)
            longest = max(bodies, key=len) if bodies else ""
            doc_cache[product] = (total, longest[:600])
        return doc_cache[product]

    t_start = time.time()
    todo = [it for it in items if it["q"] not in done]
    print(f"총 {len(items)}문항 중 {len(todo)}문항 실행")

    with OUT.open("a", encoding="utf-8") as fh:
        for i, it in enumerate(todo, 1):
            q, gold = it["q"], it["gold_product"]
            t0 = time.time()
            try:
                req = urllib.request.Request(
                    ENGINE, data=json.dumps({"question": q, "top_k": TOP_K}).encode(),
                    headers={"Content-Type": "application/json"})
                resp = json.load(urllib.request.urlopen(req, timeout=600))
                err = None
            except Exception as e:                       # 엔진 오류도 결과로 남긴다
                resp, err = {}, f"{type(e).__name__}: {e}"[:200]
            latency = round(time.time() - t0, 2)

            answer = norm(resp.get("answer"))
            sources = resp.get("sources") or []
            g = loose(gold)
            def match(k):
                for s in sources[:k]:
                    pn = loose(s.get("product_name"))
                    if pn and (pn == g or g in pn or pn in g):
                        return True
                return False
            hit1, hit5 = match(1), match(TOP_K)
            refused = REFUSAL_MARK in answer
            total_chars, excerpt = gold_doc(gold)

            if not refused:
                reason = ""
            elif not hit5:
                reason = "retrieval_miss"
            elif total_chars < EMPTY_DOC_CHARS:
                reason = "empty_source"
            else:
                reason = "false_refusal"

            rec = {
                "q": q, "category": it["category"], "variant": it.get("variant"),
                "style": it.get("style"), "gold_product": gold,
                "gold_doc_chars": total_chars, "gold_excerpt": excerpt,
                "answer": answer, "refused": refused, "refusal_reason": reason,
                "hit1": hit1, "hit5": hit5,
                "grounded": resp.get("grounded"), "violations": resp.get("violations") or [],
                "used_chunks": resp.get("used_chunks"),
                "latency_s": latency, "error": err,
                "sources": [{
                    "source_file": norm(s.get("source_file")),
                    "product_name": norm(s.get("product_name")),
                    "page": s.get("page"), "score": s.get("score"),
                    "snippet": norm(s.get("snippet"))[:300],
                } for s in sources],
            }
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
            fh.flush()

            if i % 10 == 0 or i == len(todo):
                el = time.time() - t_start
                eta = el / i * (len(todo) - i)
                print(f"  [{i}/{len(todo)}] {el/60:.0f}분 경과 · 잔여 약 {eta/60:.0f}분",
                      flush=True)

    print(f"\n완료 → {OUT}")


if __name__ == "__main__":
    main()
