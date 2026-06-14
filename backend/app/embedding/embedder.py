"""Embedding adapter with deterministic local fallback."""

from __future__ import annotations

import hashlib
import math
from typing import Iterable, List, Optional

from backend.app.config import settings
from backend.app.embedding.cache import EmbeddingCache


class Embedder:
    """Generate embeddings using sentence-transformers when available.

    If the configured model cannot be loaded, a deterministic hashing embedder is
    used. The fallback keeps tests and local PoC flows operational without model
    downloads, while preserving the same embedding interface.
    """

    def __init__(
        self,
        model_name: str = "",
        batch_size: int = 4,
        cache_path: str = "",
        fallback_dim: int = 384,
    ) -> None:
        self.model_name = model_name or settings.embedding_model
        self.batch_size = batch_size or settings.embedding_batch_size
        self.fallback_dim = fallback_dim or settings.embedding_fallback_dim
        self.cache = EmbeddingCache(cache_path or settings.embedding_cache_path)
        self._model: Optional[object] = None
        self._load_attempted = False

    def embed_texts(self, texts: Iterable[str]) -> List[List[float]]:
        """Embed texts in configured batches."""
        vectors: List[List[float]] = []
        pending: List[str] = []
        pending_indices: List[int] = []
        text_list = list(texts)
        vectors = [[] for _ in text_list]

        for index, text in enumerate(text_list):
            cached = self.cache.get(self.model_name, text)
            if cached is not None:
                vectors[index] = cached
            else:
                pending.append(text)
                pending_indices.append(index)

        for start in range(0, len(pending), self.batch_size):
            batch = pending[start : start + self.batch_size]
            batch_vectors = self._embed_uncached(batch)
            for local_index, vector in enumerate(batch_vectors):
                original_index = pending_indices[start + local_index]
                vectors[original_index] = vector
                self.cache.set(self.model_name, text_list[original_index], vector)
        return vectors

    def embed_text(self, text: str) -> List[float]:
        """Embed a single text."""
        return self.embed_texts([text])[0]

    def _embed_uncached(self, texts: List[str]) -> List[List[float]]:
        model = self._load_model()
        if model is not None:
            try:
                vectors = model.encode(texts, normalize_embeddings=True)
                return [list(map(float, vector)) for vector in vectors]
            except Exception:
                pass
        return [self._hash_embedding(text) for text in texts]

    def _load_model(self) -> Optional[object]:
        if self._load_attempted:
            return self._model
        self._load_attempted = True
        try:
            from sentence_transformers import SentenceTransformer

            self._model = SentenceTransformer(self.model_name)
        except Exception:
            self._model = None
        return self._model

    def _hash_embedding(self, text: str) -> List[float]:
        vector = [0.0] * self.fallback_dim
        tokens = [token for token in _tokenize(text) if token]
        if not tokens:
            tokens = [text or "empty"]
        for token in tokens:
            digest = hashlib.sha256(token.encode("utf-8")).digest()
            for index, byte in enumerate(digest):
                slot = (byte + index * 31) % self.fallback_dim
                vector[slot] += 1.0 if byte % 2 == 0 else -1.0
        norm = math.sqrt(sum(value * value for value in vector)) or 1.0
        return [value / norm for value in vector]


def _tokenize(text: str) -> List[str]:
    normalized = text.lower().replace("/", " ").replace("_", " ")
    return [token.strip(".,:;()[]{}'\"") for token in normalized.split()]
