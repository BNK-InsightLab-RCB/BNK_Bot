"""Elasticsearch and local JSON indexing adapter."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Iterable, List, Optional

from backend.app.config import settings
from backend.app.parsers.base import KnowledgeDocument
from backend.app.utils.logging import get_logger


logger = get_logger(__name__)


class KnowledgeIndex:
    """Write knowledge documents to local JSON and optionally Elasticsearch."""

    def __init__(
        self,
        index_name: str = "",
        local_path: str = "",
        elastic_url: str = "",
    ) -> None:
        self.index_name = index_name or settings.elastic_index
        self.local_path = Path(local_path or settings.local_index_path)
        self.elastic_url = elastic_url or settings.elastic_url
        self.local_path.parent.mkdir(parents=True, exist_ok=True)

    def reset(self) -> None:
        """Delete local index and remote Elasticsearch index if available."""
        if self.local_path.exists():
            self.local_path.unlink()
        client = self._client()
        if client is not None:
            try:
                if client.indices.exists(index=self.index_name):
                    client.indices.delete(index=self.index_name)
                    for _ in range(25):
                        if not client.indices.exists(index=self.index_name):
                            break
                        time.sleep(0.2)
            except Exception as exc:
                logger.info("Elasticsearch reset skipped: %s", exc)

    def index_documents(self, docs: Iterable[KnowledgeDocument]) -> None:
        """Persist documents to local JSON and optional Elasticsearch."""
        documents = list(docs)
        self._write_local(documents)
        self._write_elasticsearch(documents)

    def load_documents(self) -> List[KnowledgeDocument]:
        """Load documents from the local JSON fallback index."""
        if not self.local_path.exists():
            return []
        raw = json.loads(self.local_path.read_text(encoding="utf-8"))
        return [KnowledgeDocument.from_dict(item) for item in raw]

    def client(self) -> Optional[object]:
        """Return a live Elasticsearch client when available."""
        return self._client()

    def _write_local(self, docs: List[KnowledgeDocument]) -> None:
        self.local_path.write_text(
            json.dumps([doc.to_dict(include_code=True) for doc in docs], ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def _write_elasticsearch(self, docs: List[KnowledgeDocument]) -> None:
        client = self._client()
        if client is None or not docs:
            return
        try:
            self._ensure_mapping(client, len(docs[0].embedding or []))
            operations = []
            for doc in docs:
                operations.append({"index": {"_index": self.index_name, "_id": doc.id}})
                operations.append(_elastic_payload(doc))
            client.bulk(operations=operations, refresh=True)
        except Exception as exc:
            logger.info("Elasticsearch index skipped, local JSON remains available: %s", exc)

    def _ensure_mapping(self, client: object, embedding_dim: int) -> None:
        if client.indices.exists(index=self.index_name):
            return
        properties = {
            "doc_type": {"type": "keyword"},
            "system": {"type": "keyword"},
            "business_domain": {"type": "keyword"},
            "screen_id": {"type": "keyword"},
            "screen_name": {"type": "text"},
            "menu_id": {"type": "keyword"},
            "menu_name": {"type": "text"},
            "api_path": {"type": "keyword"},
            "http_method": {"type": "keyword"},
            "class_name": {"type": "keyword"},
            "method_name": {"type": "keyword"},
            "sql_id": {"type": "keyword"},
            "tables": {"type": "keyword"},
            "columns": {"type": "keyword"},
            "source_path": {"type": "keyword"},
            "error_messages": {"type": "text"},
            "business_rules": {"type": "text"},
            "possible_errors": {"type": "text"},
            "branch_guide": {"type": "text"},
            "it_guide": {"type": "text"},
            "summary": {"type": "text"},
            "code_text": {"type": "text"},
            "start_line": {"type": "integer"},
            "end_line": {"type": "integer"},
        }
        if embedding_dim:
            properties["embedding"] = {
                "type": "dense_vector",
                "dims": embedding_dim,
                "index": True,
                "similarity": "cosine",
            }
        try:
            client.indices.create(index=self.index_name, mappings={"properties": properties})
        except Exception as exc:
            if "resource_already_exists_exception" not in str(exc):
                raise

    def _client(self) -> Optional[object]:
        try:
            from elasticsearch import Elasticsearch

            client = Elasticsearch(self.elastic_url, request_timeout=2)
            if not client.ping():
                return None
            return client
        except Exception:
            return None


def _elastic_payload(doc: KnowledgeDocument) -> dict:
    payload = doc.to_dict(include_code=True)
    payload["possible_errors"] = [
        json.dumps(error, ensure_ascii=False) if isinstance(error, dict) else str(error)
        for error in doc.possible_errors
    ]
    return payload
