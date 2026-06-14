"""Retrieval-facing graph expansion."""

from __future__ import annotations

from typing import Iterable, List

from backend.app.config import settings
from backend.app.parsers.base import KnowledgeDocument
from backend.app.storage.sqlite import SQLiteGraphStore


class GraphExpander:
    """MVP graph expander.

    The graph is persisted in SQLite for inspection. For retrieval, this class
    also performs direct metadata expansion over loaded documents so the sample
    E2E path remains deterministic.
    """

    def __init__(self, sqlite_path: str = "") -> None:
        self.store = SQLiteGraphStore(sqlite_path or settings.sqlite_path)

    def expand(self, seeds: Iterable[KnowledgeDocument], all_docs: List[KnowledgeDocument]) -> List[KnowledgeDocument]:
        """Return seed docs plus related docs sharing screen, API, class, SQL, or table."""
        result = list(seeds)
        seen = {doc.id for doc in result}
        include_tables = not any(doc.screen_id or doc.screen_name or doc.api_path for doc in result)
        seed_values = _seed_values(result, include_tables=include_tables)
        for doc in all_docs:
            if doc.id in seen:
                continue
            values = _doc_values(doc, include_tables=include_tables)
            if seed_values & values:
                result.append(doc)
                seen.add(doc.id)
        return result


def _seed_values(docs: List[KnowledgeDocument], include_tables: bool = True) -> set:
    values = set()
    for doc in docs:
        values |= _doc_values(doc, include_tables=include_tables)
    return values


def _doc_values(doc: KnowledgeDocument, include_tables: bool = True) -> set:
    values = {
        doc.screen_id,
        doc.screen_name,
        doc.api_path,
        doc.method_name,
        doc.sql_id,
    }
    if include_tables:
        values.add(doc.class_name)
        values |= set(doc.tables)
    values |= set(doc.metadata.get("mapper_calls", []))
    values |= set(doc.metadata.get("service_calls", []))
    values |= set(doc.metadata.get("related_sql_ids", []))
    return {value for value in values if value}
