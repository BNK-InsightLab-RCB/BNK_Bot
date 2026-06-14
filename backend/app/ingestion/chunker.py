"""Code chunk helpers."""

from __future__ import annotations

from typing import List


def chunk_text(text: str, max_chars: int = 6000) -> List[str]:
    """Split large text on line boundaries."""
    chunks: List[str] = []
    current: List[str] = []
    size = 0
    for line in text.splitlines():
        if size + len(line) > max_chars and current:
            chunks.append("\n".join(current))
            current = []
            size = 0
        current.append(line)
        size += len(line) + 1
    if current:
        chunks.append("\n".join(current))
    return chunks
