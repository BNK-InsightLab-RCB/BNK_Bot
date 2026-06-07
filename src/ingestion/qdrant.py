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
INDEXED_FIELDS = ("category", "doc_type", "product_name", "source_file")


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

    def count(self) -> int:
        return self.client.count(self.collection, exact=True).count

    # ----- write --------------------------------------------------------------
    def _point_id(self, source_file: str, chunk_index: int) -> str:
        return str(uuid.uuid5(_NAMESPACE, f"{source_file}:{chunk_index}"))

    def upsert_chunks(self, chunks: Sequence[dict], vectors) -> int:
        """chunks: list of chunk dicts; vectors: (N, dim) array/list aligned."""
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

    def search(self, query_vector, top_k: int = 5, flt: Filter | None = None):
        vec = query_vector.tolist() if hasattr(query_vector, "tolist") else list(query_vector)
        return self.client.query_points(
            self.collection, query=vec, limit=top_k,
            query_filter=flt, with_payload=True,
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
