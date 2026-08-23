"""A/B/C 실험: 청크 컨텍스트 헤더가 검색 품질에 실제로 기여하는가? (임시 컬렉션)

**왜 재는가.** 청킹 단계에서 파일명으로 상품명을 '추출'하는 것은 원본에 없는 정보를
만들어내는 **판단**이고, 실제로 오류를 냈다(`규약_…` 로 시작하는 상품명 39건 대기 중).
그런데 이 추출이 검색에 얼마나 기여하는지는 **한 번도 측정된 적이 없다.**
가공을 유지할지 없앨지는 느낌이 아니라 이 측정으로 정한다.

변형 (임베딩되는 `text` 만 다르게 하고, payload 는 전부 동일하게 둔다 — 변수 통제)
  A: `[동백통장] · 예금/설명서`                       ← 현재 방식(정제된 상품명)
  B: `[동백통장_상품설명서(2025.11.01)] · 예금/설명서`  ← 파일명 그대로(가공 0)
  C: 헤더 없음                                        ← 본문만

채점은 `eval_retrieval.py` 의 질문셋·judge 를 그대로 재사용한다(비교 가능성 유지).
대상은 질문셋이 겨냥하는 **예금 163건**으로 한정(펀드는 질문이 없어 신호가 안 나온다).

실행:  python scripts/ab_context_header.py
결과:  logs/ab_context_header.log  (임시 컬렉션은 실행 후 삭제)
"""
from __future__ import annotations

import sys
import time
import unicodedata
from dataclasses import asdict
from datetime import datetime
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parent.parent))

from src.config import settings  # noqa: E402
from src.ingestion.embedder import Embedder  # noqa: E402
from src.ingestion.pipeline import derive_metadata, find_documents  # noqa: E402
from src.ingestion.processor import (  # noqa: E402
    KoreanFinanceProfile,
    _context_header,
    chunk_md_file,
)
from src.ingestion.qdrant import QdrantStore  # noqa: E402

sys.path.append(str(Path(__file__).resolve().parent))
from eval_retrieval import QUESTIONS, TOP_K, judge  # noqa: E402

N = lambda s: unicodedata.normalize("NFC", s)
VARIANTS = {
    "A_정제된상품명": "clean",
    "B_파일명그대로": "raw",
    "C_헤더없음": "none",
}


def build_chunks(mode: str):
    """예금 MD 전체를 청킹하고, mode 에 따라 `text`(임베딩 대상)만 바꾼다."""
    out = []
    for pdf in find_documents(settings.data_root):
        if N(pdf.parent.parent.name) != "예금":
            continue
        md = settings.processed_dir / pdf.stem / f"{pdf.stem}.md"
        if not md.exists():
            continue
        category, doc_type = (N(x) for x in derive_metadata(pdf))
        chunks = chunk_md_file(md, category=category, doc_type=doc_type)
        # ⚠️ 기본 동작(`chunk_md_file`)은 실험 결과에 따라 **raw(파일명) 로 바뀌었다.**
        #    그래서 각 변형을 기본값에 기대지 않고 **명시적으로** 만든다 — 안 그러면
        #    기본이 또 바뀔 때 A 와 B 가 같은 걸 재는 무의미한 테스트가 된다.
        for c in chunks:
            if mode == "clean":
                label = N(KoreanFinanceProfile().product_name(N(pdf.stem)))
                c.text = f"{_context_header(label, category, doc_type, c.section)}\n{c.body}"
            elif mode == "raw":
                c.text = f"{_context_header(N(pdf.stem), category, doc_type, c.section)}\n{c.body}"
            elif mode == "none":
                c.text = c.body
        out.append(chunks)
    return out


def main() -> None:
    emb = Embedder()
    lines = [f"# A/B/C 컨텍스트 헤더 실험 @ {datetime.now().isoformat(timespec='seconds')}",
             f"# 대상: 예금 문서 · 질문 {len(QUESTIONS)}개 · top-{TOP_K}", ""]

    def out(s=""):
        print(s)
        lines.append(s)

    results = {}
    for label, mode in VARIANTS.items():
        t0 = time.time()
        coll = f"ab_{mode}"
        store = QdrantStore(url=settings.qdrant_url, collection=coll,
                            dim=emb.dim, api_key=settings.qdrant_api_key)
        store.ensure_collection(recreate=True)

        n_chunks = 0
        for chunks in build_chunks(mode):
            vecs = emb.embed_texts([c.text for c in chunks])
            store.upsert_chunks([asdict(c) for c in chunks], vecs)
            n_chunks += len(chunks)
            emb.release_cache()

        p1 = p5 = 0
        detail = []
        for item in QUESTIONS:
            hits = store.search(emb.embed_query(item["q"]), top_k=TOP_K)
            ok5 = judge(hits, item.get("product"), item.get("keywords"))
            ok1 = judge(hits[:1], item.get("product"), item.get("keywords"))
            p1 += ok1
            p5 += ok5
            detail.append((ok1, ok5, item["q"], hits[0].payload["product_name"] if hits else "",
                           round(hits[0].score, 3) if hits else 0))
        results[label] = (p1, p5, n_chunks, detail, time.time() - t0)
        out(f"{label:<16} 청크 {n_chunks:,} · pass@1 {p1}/{len(QUESTIONS)} · pass@5 {p5}/{len(QUESTIONS)}"
            f"  ({time.time()-t0:.0f}초)")
        store.client.delete_collection(coll)

    out("\n== 요약 ==")
    out(f"{'변형':<16}{'pass@1':>10}{'pass@5':>10}")
    for label, (p1, p5, n, _, _) in results.items():
        out(f"{label:<16}{p1:>7}/{len(QUESTIONS)}{p5:>7}/{len(QUESTIONS)}")

    out("\n== 질문별 차이(변형 간 결과가 갈린 것만) ==")
    labels = list(results)
    for i, item in enumerate(QUESTIONS):
        vals = [(l, results[l][3][i]) for l in labels]
        if len({(v[0], v[1]) for _, v in vals}) > 1:
            out(f"  Q: {item['q']}")
            for l, (o1, o5, _, prod, sc) in vals:
                out(f"     {l:<16} @1={'O' if o1 else 'X'} @5={'O' if o5 else 'X'}  top1={prod[:22]} ({sc})")

    settings.logs_dir.mkdir(parents=True, exist_ok=True)
    (settings.logs_dir / "ab_context_header.log").write_text("\n".join(lines) + "\n", encoding="utf-8")
    out(f"\nsaved -> {settings.logs_dir/'ab_context_header.log'}")


if __name__ == "__main__":
    main()
