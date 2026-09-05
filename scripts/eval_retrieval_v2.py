"""카테고리 층화 검색 평가 — 검색 전략 A/B 비교용 (read-only).

`eval_retrieval.py`(예금 15문항, 내용 이해까지 판정)와 목적이 다르다.
이쪽은 **"특정 상품을 23만 청크에서 찾아내는가"** 하나만 카테고리별로 잰다.
문항은 `build_eval_set.py` 가 색인의 실제 product_name 으로 생성한다.

전략
----
- ``dense``  : 현재 운영 방식(임베딩 검색만)
- ``filter`` : 질의에서 고른 어휘로 body 전문검색 필터를 건 뒤 dense 로 랭킹
               (= 프로토타입 변형 Ⓑ. 컬렉션 재생성 불필요)

⚠️ RRF 융합은 프로토타입에서 **오히려 악화**됐다(53%→40%). 전문검색 인덱스는
불리언 필터라 랭킹이 없어, 임의 순서 후보를 융합하면 잡음이 상위로 올라온다.
그래서 여기 선택지에 넣지 않았다. 근거는 CLAUDE.md "Hybrid 실현가능성" 절.

실행:
    python scripts/eval_retrieval_v2.py                  # 두 전략 비교
    python scripts/eval_retrieval_v2.py --strategy dense # 하나만
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
import unicodedata
from collections import defaultdict
from datetime import datetime
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parent.parent))

from qdrant_client import models as m  # noqa: E402

from src.chat.retriever import Retriever  # noqa: E402
from src.config import settings  # noqa: E402
from src.ingestion.embedder import Embedder  # noqa: E402
from src.ingestion.qdrant import QdrantStore  # noqa: E402

TOP_K = 5
DF_MAX = 20_000        # 이보다 흔한 토큰은 필터로 써도 건초더미가 안 줄어든다
DF_MIN = 1

_TAIL = ("은", "는", "이", "가", "을", "를", "의", "에", "로", "으로", "와", "과",
         "도", "만", "이야", "인가요", "한가요", "야")
_STOP = {"알려줘", "있어", "있나요", "되나요", "어떤", "누구야", "얼마야", "상품", "펀드",
         "보험", "카드", "서비스", "조건", "대상", "내용", "방법", "기간", "가능해",
         "가입", "이용", "혜택", "금리", "수수료", "납입기간", "이체한도", "보장",
         "환매수수료", "투자위험등급", "중도해지", "중도상환수수료", "상환", "연회비",
         "신탁", "대출", "통화", "환전",
         # ── 1차 측정에서 실제로 필터로 뽑혀 정확도를 떨어뜨린 것들.
         # 의문사·서술어: 질문 어디에나 나오므로 필터로 쓰면 엉뚱한 곳으로 좁힌다.
         "어떻게", "무엇", "뭐야", "어디", "언제", "얼마", "몇", "왜", "인가", "되나",
         # 문서 종류를 가리키는 일반명사: 상품 식별력이 없다.
         "약정서", "추가약정서", "규약", "약관", "설명서", "투자설명서", "상품설명서",
         "안내장", "준법심의필", "계약서", "신청서", "통지서", "이용약관", "핵심",
         "부산은행", "모바일용", "웹용", "최종", "대면", "비대면", "개정", "적용"}

# 순수 숫자 토큰(예: "2609", "202410")도 상품 식별에 도움이 안 되고,
# 오히려 무관한 문서의 날짜·코드에 걸린다.
_NUMERIC = re.compile(r"^[0-9]+$")


def strip_tail(t: str) -> str:
    for s in sorted(_TAIL, key=len, reverse=True):
        if len(t) > len(s) + 1 and t.endswith(s):
            return t[: -len(s)]
    return t


def cand_tokens(q: str) -> list[str]:
    """필터 후보 토큰.

    ⚠️ 조사 제거형과 원형을 **둘 다** 후보에 넣는 변형을 실측했으나 악화됐다
    (pass@1 73%→62%). 후보가 늘면 df 조건을 먼저 통과하는 짧고 흔한 토큰이
    선택돼 필터가 무뎌진다. 제거형만 쓴다.
    (그 대가로 "거래한도"→"거래한" 같은 훼손 1건은 남는다.)
    """
    raw = {strip_tail(w) for w in re.findall(r"[가-힣A-Za-z0-9]{2,}", q)}
    toks = [t for t in raw
            if t not in _STOP and len(t) >= 2 and not _NUMERIC.match(t)
            # 한글 3자 이상이거나 영문 약어(HF, BNK 등)여야 상품명일 가능성이 있다.
            and (len(re.findall(r"[가-힣]", t)) >= 3 or re.fullmatch(r"[A-Za-z]{2,}", t))]
    # 길이 내림차순, 동점은 사전순. set 순회 순서에 기대면 **실행마다 결과가 달라진다**
    # (실측: 같은 코드로 78/108 과 79/108 이 번갈아 나왔다). 동점 tie-break 를 못박는다.
    return sorted(set(toks), key=lambda t: (-len(t), t))


class Searcher:
    """⚠️ 검색 로직을 **여기서 다시 구현하지 말 것.**

    이 스크립트가 자체 filtered() 를 갖고 있던 동안, retriever.py 를 고쳐도 수치가
    그대로여서 '개선 효과 없음'으로 오판할 뻔했다(같은 함정을 eval_retrieval.py 에서도
    겪었다). 운영 경로(Retriever)를 그대로 호출해야 평가가 의미를 갖는다.
    """

    def __init__(self) -> None:
        self.emb = Embedder()
        self.store = QdrantStore(url=settings.qdrant_url,
                                 collection=settings.qdrant_collection_name,
                                 dim=self.emb.dim, api_key=settings.qdrant_api_key)
        self.cli = self.store.client
        self.col = self.store.collection
        self.retriever = Retriever(self.emb, self.store)

    def df(self, tok: str) -> int:
        if tok not in self._df:
            self._df[tok] = self.cli.count(self.col, exact=True, count_filter=m.Filter(
                must=[m.FieldCondition(key="body", match=m.MatchText(text=tok))])).count
        return self._df[tok]

    def dense(self, q: str, vec, limit=TOP_K):
        return self.retriever.retrieve(q, top_k=limit, score_threshold=0.0, use_lexical=False)

    def filtered(self, q: str, vec, limit=TOP_K):
        """어휘 필터 + dense. 리랭커는 끈다(그 기여를 따로 보기 위해)."""
        hits = self.retriever.retrieve(q, top_k=limit, score_threshold=0.0,
                                       use_reranker=False)
        picked = self.retriever._pick_filter(q)
        return hits, (picked[1] if picked else None)

    def reranked(self, q: str, vec, limit=TOP_K):
        """운영 경로 전체(어휘 필터 + dense + 리랭커)."""
        return self.retriever.retrieve(q, top_k=limit, score_threshold=0.0), None


def _norm_name(s: str) -> str:
    """상품명 비교용 정규화 — **띄어쓰기·문장부호를 무시한다.**

    ⚠️ 이걸 안 하면 **검색은 맞았는데 오답으로 집계된다.** 실측 사례:
        정답 "계좌통합관리서비스이용" / 1등 "계좌통합관리서비스 이용"  ← 같은 문서다
    적재 단계의 상품명 추출이 같은 문서를 띄어쓰기만 다르게 뽑아 놓은 결과이고,
    검색 품질과는 무관하다. 이걸 실패로 세면 **없는 개선 여지를 있는 것처럼 보이게 한다**
    (실제로 그렇게 보여서 리랭커를 붙였다가 +2문항밖에 못 얻었다).
    """
    return re.sub(r"[\s\-_·.,()\[\]{}/]+", "", unicodedata.normalize("NFC", s))


def hit(points, gold: str, k: int) -> bool:
    g = _norm_name(gold)
    if not g:
        return False
    for p in points[:k]:
        pn = _norm_name(str(p.payload.get("product_name") or ""))
        if pn and (pn == g or g in pn or pn in g):
            return True
    return False


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--set", default="eval/eval_set.json")
    ap.add_argument("--strategy", choices=["dense", "filter", "rerank", "all"], default="all")
    args = ap.parse_args()

    data = json.loads(Path(args.set).read_text(encoding="utf-8"))
    items = data["items"]
    s = Searcher()
    strategies = ["dense", "filter", "rerank"] if args.strategy == "all" else [args.strategy]

    agg: dict[str, dict[str, list[int]]] = {st: defaultdict(list) for st in strategies}
    rows: list[str] = []
    t0 = time.time()

    for it in items:
        q, gold, cat = it["q"], it["gold_product"], it["category"]
        vec = s.emb.embed_texts([q])[0].tolist()
        res = {}
        for st in strategies:
            fn = {"dense": s.dense, "filter": s.filtered, "rerank": s.reranked}[st]
            out = fn(q, vec)
            pts, tok = out if isinstance(out, tuple) else (out, None)
            res[st] = (hit(pts, gold, 1), hit(pts, gold, TOP_K), tok,
                       str(pts[0].payload.get("product_name")) if pts else "")
            agg[st][cat].append(res[st][0])
            agg[st]["_all"].append(res[st][0])
            agg[st][cat + "@5"].append(res[st][1])
            agg[st]["_all@5"].append(res[st][1])
            # 문항 성격별 집계: 상품명이 정확히 든 질문(exact)과 고객 말투로 변형한
            # 질문(realistic)은 난이도가 다르다. 섞어서 하나의 수치로 보면 안 된다.
            agg[st]["s:" + it.get("style", "?")].append(res[st][0])
            agg[st]["v:" + it.get("variant", "?")].append(res[st][0])
            agg[st]["s5:" + it.get("style", "?")].append(res[st][1])
        if "dense" in res and "filter" in res and len(strategies) == 2:
            d, f = res["dense"][0], res["filter"][0]
            mark = "  " if d == f else ("🔺" if f else "🔻")
            rows.append(f"{mark} [{cat:<4}] d@1={'O' if d else 'X'} f@1={'O' if f else 'X'}"
                        f" tok={res['filter'][2] or '폴백':<14} :: {q[:44]}")

    def pct(xs):
        return f"{sum(xs)}/{len(xs)} ({100*sum(xs)//len(xs)}%)" if xs else "-"

    lines = [f"# eval_retrieval_v2 @ {datetime.now().isoformat(timespec='seconds')}",
             f"# 문항 {len(items)} · 카테고리 층화 · seed={data['seed']} · top_k={TOP_K}",
             "# 재는 것: '특정 상품을 23만 청크에서 찾아내는가' (내용 이해는 eval_answer.py)"]
    if rows:
        lines += ["", "== 전략별 차이(변화만 표시) =="] + [r for r in rows if r[0] != " "]
    lines += ["", f"== 카테고리별 pass@1 =="]
    cats = sorted({it["category"] for it in items})
    head = f"  {'카테고리':<8}" + "".join(f"{st:>16}" for st in strategies)
    lines.append(head)
    for c in cats:
        lines.append(f"  {c:<8}" + "".join(f"{pct(agg[st][c]):>16}" for st in strategies))
    lines.append(f"  {'—전체—':<8}" + "".join(f"{pct(agg[st]['_all']):>16}" for st in strategies))
    lines.append("")
    lines.append(f"  {'전체 pass@5':<8}" + "".join(f"{pct(agg[st]['_all@5']):>16}" for st in strategies))

    lines += ["", "== 문항 성격별 pass@1 =="]
    lines.append(f"  {'성격':<14}" + "".join(f"{st:>16}" for st in strategies))
    for key, label in [("s:exact", "정확형(상품명 그대로)"), ("s:realistic", "실전형(말투 변형)")]:
        if agg[strategies[0]].get(key):
            lines.append(f"  {label:<14}" + "".join(f"{pct(agg[st][key]):>16}" for st in strategies))
    lines.append("")
    lines.append(f"  {'변형별':<14}" + "".join(f"{st:>16}" for st in strategies))
    for key in sorted(k for k in agg[strategies[0]] if k.startswith("v:")):
        lines.append(f"  {key[2:]:<14}" + "".join(f"{pct(agg[st][key]):>16}" for st in strategies))
    lines += ["", "  전략: dense=임베딩만 · filter=어휘필터+dense · rerank=거기에 재순위까지(운영 경로)"]
    lines.append(f"\n소요 {time.time()-t0:.1f}s ({(time.time()-t0)/len(items):.2f}s/문항)")

    report = "\n".join(lines)
    print(report)
    settings.logs_dir.mkdir(parents=True, exist_ok=True)
    (settings.logs_dir / "eval_retrieval_v2.log").write_text(report, encoding="utf-8")
    print(f"\nsaved -> {settings.logs_dir / 'eval_retrieval_v2.log'}")


if __name__ == "__main__":
    main()
