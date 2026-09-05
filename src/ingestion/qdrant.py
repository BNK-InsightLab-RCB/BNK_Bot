"""Qdrant vector store — single collection with payload-based partitioning.

Design decision: ALL documents (예금/펀드/신탁/대출/카드/보험/외환/전자금융/기타 ×
약관/설명서) live in ONE collection. Categories and doc types are payload fields
(``category``, ``doc_type``, ``product_name``) with payload indexes, so we filter
within the collection instead of splitting into many collections. This keeps
cross-category search trivial, lets new categories arrive as new payload values
(no schema/collection change), and keeps ops/config single.

This module only handles storage + search. Embedding lives in ``embedder.py``;
the two are wired together by the pipeline / callers, not by importing each
other.
"""
from __future__ import annotations

import unicodedata
import uuid
from typing import Any, Sequence

from qdrant_client import QdrantClient
from qdrant_client.models import (
    Distance,
    FieldCondition,
    Filter,
    MatchValue,
    PayloadSchemaType,
    PointStruct,
    TextIndexParams,
    TokenizerType,
    VectorParams,
)

# Fixed namespace so the same (source_file, chunk_index) always maps to the same
# point id -> re-ingesting a document overwrites instead of duplicating.
_NAMESPACE = uuid.uuid5(uuid.NAMESPACE_DNS, "bnk_bot")

# Payload fields stored per point; the first ones are indexed for fast filtering.
PAYLOAD_FIELDS = (
    "product_name", "category", "doc_type", "source_file",
    "page", "section", "kind", "chunk_index", "body",
)
# keyword(정확일치) 인덱스를 거는 필드. ``build_filter`` 가 쓰는 것들이다.
INDEXED_FIELDS = ("category", "doc_type", "product_name")

# 전문검색(부분일치) 인덱스를 거는 필드 — 어휘 필터(hybrid)용. `src/chat/lexical.py` 참조.
#
# ⚠️ ``source_file`` 이 여기 있는 이유가 핵심이다. 청크에 붙는 컨텍스트 헤더
# `[파일명] · 카테고리/문서종류` 는 **임베딩 텍스트에만** 들어가고 payload ``body`` 에는
# 없다. 그래서 body 만 전문검색하면 **상품명이 본문에 안 나오는 문서를 영원히 못 찾는다**
# (실측: pass@1 실패 28건 중 24건이 이 경우 — 보험 안내장·카드·외환 약정서 등
# 상품명이 파일명에만 있는 문서들). source_file 을 검색 대상에 넣어 그 고리를 잇는다.
#
# source_file 은 keyword 가 아니라 text 로 잡는다 — 정확일치로 필터하는 코드가 없고
# (표시·감사용으로 읽기만 한다) 부분일치가 필요하기 때문이다.
#
# 토크나이저가 필드마다 다른 이유:
#   source_file → PREFIX. 전문검색은 **토큰 단위**로만 맞아서, 고객이 띄어 쓰면
#     ("유스타일정기예금" → "유스타일 정기예금") 어느 토큰도 파일명과 일치하지 않는다.
#     그러면 흔한 토큰("정기예금")으로 엉뚱하게 좁혀 **dense 단독보다 나빠진다**.
#     PREFIX 는 접두사를 색인해 부분일치를 가능하게 한다.
#     실측(1,302문항): 전체 65%→**80%**, 띄어쓰기 변형 55%→**75%**, 부분명 49%→**77%**.
#     비용 2.0초 · 디스크 증가 없음(파일명은 짧다).
#   body → MULTILINGUAL. 본문은 양이 커서 PREFIX 로 접두사를 전부 펼치면 색인이
#     커진다. **미검증이므로 바꾸지 말 것** — 필요하면 크기·시간을 먼저 재라.
TEXT_INDEXED_FIELDS = {
    "body": TokenizerType.MULTILINGUAL,
    "source_file": TokenizerType.PREFIX,
}


class QdrantStore:
    def __init__(
        self,
        url: str,
        collection: str,
        dim: int = 1024,
        api_key: str | None = None,
        distance: Distance = Distance.COSINE,
    ):
        self.client = QdrantClient(url=url, api_key=api_key)
        self.collection = collection
        self.dim = dim
        self.distance = distance

    # ----- collection lifecycle ----------------------------------------------
    def ensure_collection(self, recreate: bool = False) -> None:
        exists = self.client.collection_exists(self.collection)
        if exists and recreate:
            self.client.delete_collection(self.collection)
            exists = False
        if not exists:
            self.client.create_collection(
                self.collection,
                vectors_config=VectorParams(size=self.dim, distance=self.distance),
            )
        for field in INDEXED_FIELDS:  # idempotent; ignore "already exists"
            try:
                self.client.create_payload_index(
                    self.collection, field_name=field,
                    field_schema=PayloadSchemaType.KEYWORD,
                )
            except Exception:
                pass
        for field, tokenizer in TEXT_INDEXED_FIELDS.items():
            try:
                self.client.create_payload_index(
                    self.collection, field_name=field,
                    field_schema=TextIndexParams(
                        type="text", tokenizer=tokenizer,
                        min_token_len=2, max_token_len=30, lowercase=True),
                )
            except Exception:
                pass

    def count(self) -> int:
        return self.client.count(self.collection, exact=True).count

    # ----- write --------------------------------------------------------------
    def _point_id(self, source_file: str, chunk_index: int) -> str:
        return str(uuid.uuid5(_NAMESPACE, f"{source_file}:{chunk_index}"))

    def upsert_chunks(self, chunks: Sequence[dict], vectors) -> int:
        """chunks: list of chunk dicts; vectors: (N, dim) array/list aligned.

        청크가 0개면 **Qdrant 를 호출하지 않고** 0 을 반환한다. 빈 points 를 보내면
        Qdrant 가 `400 Bad request: Empty update request` 로 거절하고, 파이프라인은
        이를 '문서 처리 실패'로 기록한다 — 실제로는 실패가 아니라 **추출할 텍스트가
        없는 문서**인데도.

        실측: 카드 안내장 45건이 이 경로로 죽었다. 글자가 벡터 도형으로 그려진
        디자인 리플렛이라 텍스트레이어가 없고, Docling 이 남긴 `<!-- image -->`
        placeholder 를 청커가 정상적으로 제거하자 청크가 0개가 됐다.
        (해당 문서를 실제로 색인하려면 OCR 쪽 대응이 따로 필요하다 — 이 가드는
         '오류로 죽지 않게' 할 뿐 문서를 살리지는 못한다.)
        """
        if not chunks:
            return 0
        points = []
        for c, v in zip(chunks, vectors):
            payload = {k: c.get(k) for k in PAYLOAD_FIELDS}
            vec = v.tolist() if hasattr(v, "tolist") else list(v)
            points.append(
                PointStruct(
                    id=self._point_id(c["source_file"], c["chunk_index"]),
                    vector=vec,
                    payload=payload,
                )
            )
        self.client.upsert(self.collection, points=points)
        return len(points)

    # ----- read ---------------------------------------------------------------
    @staticmethod
    def build_filter(**equals: Any) -> Filter | None:
        def _norm(v):  # match NFC-normalised stored payload (macOS NFD safety)
            return unicodedata.normalize("NFC", v) if isinstance(v, str) else v

        conds = [
            FieldCondition(key=k, match=MatchValue(value=_norm(v)))
            for k, v in equals.items() if v is not None
        ]
        return Filter(must=conds) if conds else None

    def search(
        self,
        query_vector,
        top_k: int = 5,
        flt: Filter | None = None,
        score_threshold: float | None = None,
    ):
        """top-k 검색. ``score_threshold`` 아래 결과는 Qdrant 가 제외한다.

        임계가 없으면 질문이 아무리 무관해도 항상 top_k 가 채워져 나온다 —
        그러면 "근거 없음" 판단이 LLM 몫이 된다. 임계를 주면 **빈 리스트**가 돌아와
        호출부(`ChatService`)가 LLM 없이 즉시 거부할 수 있다.
        """
        vec = query_vector.tolist() if hasattr(query_vector, "tolist") else list(query_vector)
        return self.client.query_points(
            self.collection, query=vec, limit=top_k,
            query_filter=flt, with_payload=True,
            score_threshold=score_threshold,
        ).points


if __name__ == "__main__":
    import json
    import sys
    from pathlib import Path

    sys.path.append(str(Path(__file__).parent.parent.parent))
    from src.config import settings
    from src.ingestion.embedder import Embedder

    jsonl = next(settings.chunks_dir.glob("*.jsonl"))
    chunks = [json.loads(l) for l in jsonl.open(encoding="utf-8")]
    print(f"chunks: {len(chunks)} from {jsonl.name}")

    emb = Embedder()
    vecs = emb.embed_texts([c["text"] for c in chunks])

    store = QdrantStore(
        url=settings.qdrant_url,
        collection=settings.qdrant_collection_name,
        dim=emb.dim,
        api_key=settings.qdrant_api_key,
    )
    store.ensure_collection(recreate=True)
    n = store.upsert_chunks(chunks, vecs)
    print(f"upserted {n} -> collection '{store.collection}', count={store.count()}")

    queries = [
        "9개월 미만에 중도해지하면 이율이 어떻게 되나요?",
        "이 예금을 양도할 수 있나요?",
        "예금자 보호가 되는 상품인가요?",
    ]
    print("\n=== Qdrant search (top-3) ===")
    for q in queries:
        hits = store.search(emb.embed_query(q), top_k=3)
        print(f"\nQ: {q}")
        for h in hits:
            p = h.payload
            print(f"  score={h.score:.3f} [{p['chunk_index']}] {p['section'][:8]:8} | {p['body'][:55].replace(chr(10),' ')}")

    print("\n=== payload 예시 (top-1) ===")
    h = store.search(emb.embed_query(queries[0]), top_k=1)[0]
    print(json.dumps({k: h.payload[k] for k in ("product_name", "category", "doc_type", "page", "section")}, ensure_ascii=False))

    print("\n=== 필터 검색 (category=예금) ===")
    flt = QdrantStore.build_filter(category="예금")
    hits = store.search(emb.embed_query("예금자 보호"), top_k=2, flt=flt)
    for h in hits:
        print(f"  score={h.score:.3f} category={h.payload['category']} | {h.payload['body'][:45]}")
