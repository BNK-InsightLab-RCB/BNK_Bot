from __future__ import annotations

from dataclasses import dataclass
from threading import Lock


@dataclass
class GenerationResult:
    text: str
    model: str


class MlxQwenClient:
    def __init__(self, model_path: str) -> None:
        self.model_path = model_path
        self._model = None
        self._tokenizer = None
        self._lock = Lock()

    def load(self) -> None:
        if self._model is not None and self._tokenizer is not None:
            return

        # Lazy import keeps non-MLX routes usable in headless/sandboxed sessions.
        from mlx_lm import load

        self._model, self._tokenizer = load(self.model_path)

    def generate(self, prompt: str, max_tokens: int = 1024) -> GenerationResult:
        self.load()

        from mlx_lm import generate

        with self._lock:
            text = generate(
                self._model,
                self._tokenizer,
                prompt=prompt,
                verbose=False,
                max_tokens=max_tokens,
            )
        return GenerationResult(text=text.strip(), model=self.model_path)

