"""Text helpers and security masking."""

from __future__ import annotations

import re
from typing import Iterable, List


SENSITIVE_PATTERNS = [
    re.compile(r"(?i)(password|passwd|pwd)\s*[:=]\s*['\"]?[^'\"\s]+"),
    re.compile(r"(?i)(secret|token|api_key|access_key|private_key)\s*[:=]\s*['\"]?[^'\"\s]+"),
    re.compile(r"(?i)jdbc:[^\s'\";]+"),
    re.compile(r"\b(?:10|172\.(?:1[6-9]|2\d|3[0-1])|192\.168)\.\d{1,3}\.\d{1,3}\b"),
]


def normalize_ws(text: str) -> str:
    """Collapse repeated whitespace."""
    return re.sub(r"\s+", " ", text or "").strip()


def unique_keep_order(values: Iterable[str]) -> List[str]:
    """Return unique non-empty values while preserving input order."""
    seen = set()
    result: List[str] = []
    for value in values:
        cleaned = normalize_ws(str(value))
        if cleaned and cleaned not in seen:
            seen.add(cleaned)
            result.append(cleaned)
    return result


def mask_sensitive(text: str) -> str:
    """Mask common secrets and internal connection values."""
    masked = text or ""
    for pattern in SENSITIVE_PATTERNS:
        masked = pattern.sub(_mask_match, masked)
    return masked


def _mask_match(match: re.Match) -> str:
    raw = match.group(0)
    if "=" in raw:
        return raw.split("=", 1)[0].rstrip() + "=***"
    if ":" in raw and not raw.lower().startswith("jdbc:"):
        return raw.split(":", 1)[0].rstrip() + ":***"
    return "***"


def strip_code_fence(text: str) -> str:
    """Remove Markdown code fences when an LLM returns JSON in a fenced block."""
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
        cleaned = re.sub(r"\s*```$", "", cleaned)
    return cleaned.strip()
