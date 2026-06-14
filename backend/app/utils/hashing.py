"""Hash helpers."""

from __future__ import annotations

import hashlib
import json
from typing import Any


def stable_hash(value: str, length: int = 16) -> str:
    """Return a deterministic short hash for stable document IDs."""
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:length]


def stable_id(prefix: str, *parts: Any) -> str:
    """Build a stable ID from JSON-serializable parts."""
    text = json.dumps(parts, ensure_ascii=False, sort_keys=True, default=str)
    return f"{prefix}_{stable_hash(text)}"
