"""Embedding generation with KURE-v1 (Korean retrieval, BGE-M3 based).

Produces normalised 1024-dim vectors so downstream similarity is plain cosine
(= dot product). This module ONLY turns text into vectors — it never talks to
the vector DB (that is ``qdrant.py``'s job), keeping embedding and storage
strictly separated.

KURE-v1 is BGE-M3 based: 8192-token context (long table chunks fit whole) and
no query/passage instruction prefix is required, so queries and chunks are
encoded the same way.
"""
from __future__ import annotations

import numpy as np

DEFAULT_MODEL = "nlpai-lab/KURE-v1"


class Embedder:
    def __init__(
        self,
        model_name: str = DEFAULT_MODEL,
        device: str | None = None,
        batch_size: int = 16,
    ):
        self.model_name = model_name
        self.device = device
        self.batch_size = batch_size
        self._model = None  # lazy: model load is heavy (~2GB)

    @property
    def model(self):
        if self._model is None:
            from sentence_transformers import SentenceTransformer

            self._model = SentenceTransformer(self.model_name, device=self.device)
        return self._model

    @property
    def dim(self) -> int:
        m = self.model
        fn = getattr(m, "get_embedding_dimension", None) or m.get_sentence_embedding_dimension
        return int(fn())

    def embed_texts(self, texts: list[str], batch_size: int | None = None) -> np.ndarray:
        """Return an (N, dim) float32 array of L2-normalised embeddings."""
        return self.model.encode(
            texts,
            batch_size=batch_size or self.batch_size,
            normalize_embeddings=True,
            convert_to_numpy=True,
            show_progress_bar=False,
        )

    def embed_query(self, text: str) -> np.ndarray:
        """Return a single (dim,) vector. Same encoding as chunks (no prefix)."""
        return self.embed_texts([text])[0]

    def release_cache(self) -> None:
        """가속기(MPS/CUDA) 할당 캐시를 반환한다. **긴 배치에서 필수.**

        왜: PyTorch 는 해제한 텐서 메모리를 OS 로 바로 돌려주지 않고 캐시로 들고 있다.
        문서 1건이면 무해하지만 수백 건을 한 프로세스에서 돌리면 캐시가 단조 증가해
        후반부에 OOM 이 난다 — 실제로 펀드 배치 58건째에서
        ``MPS backend out of memory (MPS allocated: 12.14 GiB ...)`` 로 2건이 실패했다.
        청크가 커서가 아니라(최대 4.5천자) **누적**이 원인이라 배치 중간에 비워야 한다.

        호출 위치는 배치 소유자(`pipeline.ingest_paths`)이며, 문서 1건이 끝날 때마다
        부른다. ``/query`` 경로(단건 임베딩)에서는 부르지 않는다 — 지연만 늘고 이득이 없다.
        """
        try:
            import torch

            if torch.backends.mps.is_available():
                torch.mps.empty_cache()
            elif torch.cuda.is_available():
                torch.cuda.empty_cache()
        except Exception:  # 캐시 반환 실패가 적재를 멈출 이유는 없다
            pass


if __name__ == "__main__":
    import json
    import sys
    from pathlib import Path

    sys.path.append(str(Path(__file__).parent.parent.parent))
    from src.config import settings

    # Load sample chunks produced by processor.py
    jsonl = next(settings.chunks_dir.glob("*.jsonl"))
    chunks = [json.loads(l) for l in jsonl.open(encoding="utf-8")]
    texts = [c["text"] for c in chunks]
    print(f"chunks: {len(chunks)} from {jsonl.name}")

    emb = Embedder()
    vecs = emb.embed_texts(texts)
    norms = np.linalg.norm(vecs, axis=1)
    print(f"dim={emb.dim}  shape={vecs.shape}  L2 norm min/max={norms.min():.4f}/{norms.max():.4f}")

    # --- sanity retrieval (in-memory cosine; no Qdrant yet) ---
    queries = [
        "9개월 미만에 중도해지하면 이율이 어떻게 되나요?",
        "이 예금을 양도할 수 있나요?",
        "예금자 보호가 되는 상품인가요?",
        "분할해지(분할인출)가 가능한가요?",
        "기본이율이 얼마인가요?",
    ]
    print("\n=== sanity retrieval (top-3) ===")
    for q in queries:
        qv = emb.embed_query(q)
        scores = vecs @ qv  # normalised -> cosine
        top = np.argsort(-scores)[:3]
        print(f"\nQ: {q}")
        for rank, i in enumerate(top, 1):
            c = chunks[i]
            snippet = c["body"].replace("\n", " ")[:60]
            print(f"  {rank}. [{i}] {c['section'][:8]:8} {c['kind']:5} score={scores[i]:.3f} | {snippet}")
