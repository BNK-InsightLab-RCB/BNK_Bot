"""SQLite entity and relation graph store."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Dict, Iterable, List, Tuple

from backend.app.parsers.base import KnowledgeDocument
from backend.app.utils.hashing import stable_id


class SQLiteGraphStore:
    """Persist source-derived entities and relations."""

    def __init__(self, path: str) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._init()

    def _init(self) -> None:
        with sqlite3.connect(self.path) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS entities (
                    id TEXT PRIMARY KEY,
                    entity_type TEXT NOT NULL,
                    name TEXT NOT NULL,
                    normalized_name TEXT,
                    metadata_json TEXT,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS relations (
                    id TEXT PRIMARY KEY,
                    source_entity_id TEXT NOT NULL,
                    target_entity_id TEXT NOT NULL,
                    relation_type TEXT NOT NULL,
                    confidence REAL DEFAULT 1.0,
                    evidence_json TEXT,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
                """
            )

    def reset(self) -> None:
        """Delete all graph rows."""
        with sqlite3.connect(self.path) as conn:
            conn.execute("DELETE FROM relations")
            conn.execute("DELETE FROM entities")

    def upsert_entity(self, entity_type: str, name: str, metadata: Dict[str, object]) -> str:
        """Create or update an entity."""
        entity_id = stable_id("ent", entity_type, name)
        normalized = name.lower()
        with sqlite3.connect(self.path) as conn:
            conn.execute(
                """
                INSERT INTO entities (id, entity_type, name, normalized_name, metadata_json)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    metadata_json = excluded.metadata_json,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (entity_id, entity_type, name, normalized, json.dumps(metadata, ensure_ascii=False)),
            )
        return entity_id

    def upsert_relation(
        self,
        source_entity_id: str,
        target_entity_id: str,
        relation_type: str,
        evidence: Dict[str, object],
        confidence: float = 1.0,
    ) -> str:
        """Create or update a relation."""
        relation_id = stable_id("rel", source_entity_id, target_entity_id, relation_type)
        with sqlite3.connect(self.path) as conn:
            conn.execute(
                """
                INSERT INTO relations (
                    id, source_entity_id, target_entity_id, relation_type, confidence, evidence_json
                )
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    confidence = excluded.confidence,
                    evidence_json = excluded.evidence_json,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (
                    relation_id,
                    source_entity_id,
                    target_entity_id,
                    relation_type,
                    confidence,
                    json.dumps(evidence, ensure_ascii=False),
                ),
            )
        return relation_id

    def build_from_documents(self, docs: Iterable[KnowledgeDocument]) -> None:
        """Infer MVP graph entities and relations from indexed documents."""
        api_entities: Dict[str, str] = {}
        controller_entities: Dict[str, str] = {}
        service_entities: Dict[str, str] = {}
        mapper_entities: Dict[str, str] = {}
        sql_entities: Dict[str, str] = {}

        for doc in docs:
            doc_entity = self.upsert_entity("DOCUMENT", doc.id or doc.title, doc.to_dict(False))
            if doc.screen_id or doc.screen_name:
                screen_name = doc.screen_id or doc.screen_name or ""
                screen_entity = self.upsert_entity("SCREEN", screen_name, doc.to_dict(False))
                self.upsert_relation(screen_entity, doc_entity, "SCREEN_HAS_FRONTEND", {"doc_id": doc.id})
            if doc.api_path:
                api_entity = api_entities.setdefault(
                    doc.api_path,
                    self.upsert_entity("API", doc.api_path, {"api_path": doc.api_path}),
                )
                if doc.doc_type == "frontend_event":
                    self.upsert_relation(doc_entity, api_entity, "FRONTEND_CALLS_API", {"doc_id": doc.id})
                if doc.doc_type == "backend_controller":
                    controller_name = f"{doc.class_name}.{doc.method_name}"
                    controller_entity = controller_entities.setdefault(
                        controller_name,
                        self.upsert_entity("CONTROLLER", controller_name, doc.to_dict(False)),
                    )
                    self.upsert_relation(api_entity, controller_entity, "API_HANDLED_BY_CONTROLLER", {"doc_id": doc.id})
            if doc.class_name and doc.method_name:
                method_name = f"{doc.class_name}.{doc.method_name}"
                entity_type = "SERVICE" if doc.doc_type == "business_logic" else "METHOD"
                method_entity = service_entities.setdefault(
                    method_name,
                    self.upsert_entity(entity_type, method_name, doc.to_dict(False)),
                )
                for call in doc.metadata.get("mapper_calls", []):
                    mapper_entity = mapper_entities.setdefault(
                        call, self.upsert_entity("MAPPER_METHOD", call, {"name": call})
                    )
                    self.upsert_relation(method_entity, mapper_entity, "SERVICE_CALLS_MAPPER", {"doc_id": doc.id})
                for error in doc.error_messages:
                    error_entity = self.upsert_entity("ERROR", error, {"message": error})
                    self.upsert_relation(method_entity, error_entity, "LOGIC_THROWS_ERROR", {"doc_id": doc.id})
            if doc.sql_id:
                sql_entity = sql_entities.setdefault(
                    doc.sql_id,
                    self.upsert_entity("SQL", doc.sql_id, doc.to_dict(False)),
                )
                for table in doc.tables:
                    table_entity = self.upsert_entity("TABLE", table, {"table": table})
                    self.upsert_relation(sql_entity, table_entity, "SQL_USES_TABLE", {"doc_id": doc.id})

    def neighbors(self, entity_ids: Iterable[str], limit: int = 20) -> List[Tuple[str, str, str]]:
        """Return neighboring relation triples."""
        ids = list(entity_ids)
        if not ids:
            return []
        placeholders = ",".join("?" for _ in ids)
        with sqlite3.connect(self.path) as conn:
            rows = conn.execute(
                f"""
                SELECT source_entity_id, relation_type, target_entity_id
                FROM relations
                WHERE source_entity_id IN ({placeholders}) OR target_entity_id IN ({placeholders})
                LIMIT ?
                """,
                ids + ids + [limit],
            ).fetchall()
        return [(row[0], row[1], row[2]) for row in rows]
