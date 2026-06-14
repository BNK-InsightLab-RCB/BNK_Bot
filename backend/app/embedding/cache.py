"""SQLite embedding cache."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import List, Optional

from backend.app.utils.hashing import stable_hash


class EmbeddingCache:
    """Small SQLite cache keyed by model and text hash."""

    def __init__(self, path: str) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._init()

    def _init(self) -> None:
        with sqlite3.connect(self.path) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS embeddings (
                    key TEXT PRIMARY KEY,
                    vector_json TEXT NOT NULL
                )
                """
            )

    def key(self, model: str, text: str) -> str:
        """Return a cache key."""
        return stable_hash(f"{model}:{text}", length=40)

    def get(self, model: str, text: str) -> Optional[List[float]]:
        """Return cached vector if present."""
        key = self.key(model, text)
        with sqlite3.connect(self.path) as conn:
            row = conn.execute("SELECT vector_json FROM embeddings WHERE key = ?", (key,)).fetchone()
        return json.loads(row[0]) if row else None

    def set(self, model: str, text: str, vector: List[float]) -> None:
        """Persist a vector."""
        key = self.key(model, text)
        with sqlite3.connect(self.path) as conn:
            conn.execute(
                "INSERT OR REPLACE INTO embeddings (key, vector_json) VALUES (?, ?)",
                (key, json.dumps(vector)),
            )
