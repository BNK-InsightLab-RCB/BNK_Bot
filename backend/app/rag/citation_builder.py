"""Source citation builder."""

from __future__ import annotations

from typing import Iterable, List

from backend.app.parsers.base import KnowledgeDocument
from backend.app.rag.safety import sanitize_source


class CitationBuilder:
    """Build role-aware source citations."""

    def build(self, docs: Iterable[KnowledgeDocument], user_role: str) -> List[dict]:
        """Return deduplicated source citations."""
        citations = []
        seen = set()
        for doc in docs:
            if doc.id in seen:
                continue
            seen.add(doc.id)
            citations.append(sanitize_source(doc, user_role))
        return citations
