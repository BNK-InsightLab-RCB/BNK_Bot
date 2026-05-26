from __future__ import annotations

from pathlib import Path
from typing import Iterable

import torch
from sentence_transformers import SentenceTransformer


class KureEmbedder:
    def __init__(self, model_path: str) -> None:
        resolved_model_path = self._resolve_model_path(model_path)
        self.model = SentenceTransformer(resolved_model_path, device=self._device())

    def encode(self, texts: Iterable[str], batch_size: int = 16) -> list[list[float]]:
        embeddings = self.model.encode(
            list(texts),
            batch_size=batch_size,
            normalize_embeddings=True,
            show_progress_bar=True,
        )
        return embeddings.tolist()

    @staticmethod
    def _resolve_model_path(model_path: str) -> str:
        path = Path(model_path)
        if path.exists():
            return str(path)
        return "nlpai-lab/KURE-v1"

    @staticmethod
    def _device() -> str:
        if torch.cuda.is_available():
            return "cuda"
        if torch.backends.mps.is_available():
            return "mps"
        return "cpu"

