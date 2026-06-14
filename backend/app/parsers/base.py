"""Shared parser data structures."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from backend.app.utils.hashing import stable_id
from backend.app.utils.text import mask_sensitive, unique_keep_order


@dataclass
class SourceFile:
    """Source file loaded by the scanner."""

    path: Path
    language: str
    text: str


@dataclass
class KnowledgeDocument:
    """Searchable knowledge unit generated from source analysis."""

    doc_type: str
    title: str
    source_path: str
    summary: str = ""
    id: Optional[str] = None
    system: str = "bank_sample"
    business_domain: str = "branch_ops"
    screen_id: Optional[str] = None
    screen_name: Optional[str] = None
    menu_id: Optional[str] = None
    menu_name: Optional[str] = None
    api_path: Optional[str] = None
    http_method: Optional[str] = None
    class_name: Optional[str] = None
    method_name: Optional[str] = None
    sql_id: Optional[str] = None
    tables: List[str] = field(default_factory=list)
    columns: List[str] = field(default_factory=list)
    error_codes: List[str] = field(default_factory=list)
    error_messages: List[str] = field(default_factory=list)
    business_rules: List[str] = field(default_factory=list)
    possible_errors: List[Dict[str, Any]] = field(default_factory=list)
    branch_guide: str = ""
    it_guide: str = ""
    code_text: str = ""
    start_line: int = 1
    end_line: int = 1
    commit_hash: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    embedding: List[float] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.tables = unique_keep_order(self.tables)
        self.columns = unique_keep_order(self.columns)
        self.error_codes = unique_keep_order(self.error_codes)
        self.error_messages = unique_keep_order(self.error_messages)
        self.business_rules = unique_keep_order(self.business_rules)
        if self.id is None:
            self.id = stable_id(
                "doc",
                self.doc_type,
                self.source_path,
                self.title,
                self.start_line,
                self.end_line,
            )
        self.code_text = mask_sensitive(self.code_text)

    def searchable_text(self) -> str:
        """Text used for embeddings and fallback BM25."""
        parts = [
            self.title,
            self.screen_id or "",
            self.screen_name or "",
            self.menu_id or "",
            self.api_path or "",
            self.class_name or "",
            self.method_name or "",
            self.sql_id or "",
            " ".join(self.tables),
            " ".join(self.error_messages),
            " ".join(self.business_rules),
            self.branch_guide,
            self.it_guide,
            self.summary,
        ]
        return "\n".join(part for part in parts if part)

    def to_dict(self, include_code: bool = True) -> Dict[str, Any]:
        """Serialize for JSON, API, and Elasticsearch."""
        data: Dict[str, Any] = {
            "id": self.id,
            "doc_type": self.doc_type,
            "system": self.system,
            "business_domain": self.business_domain,
            "title": self.title,
            "screen_id": self.screen_id,
            "screen_name": self.screen_name,
            "menu_id": self.menu_id,
            "menu_name": self.menu_name,
            "api_path": self.api_path,
            "http_method": self.http_method,
            "class_name": self.class_name,
            "method_name": self.method_name,
            "sql_id": self.sql_id,
            "tables": self.tables,
            "columns": self.columns,
            "error_codes": self.error_codes,
            "error_messages": self.error_messages,
            "business_rules": self.business_rules,
            "possible_errors": self.possible_errors,
            "branch_guide": self.branch_guide,
            "it_guide": self.it_guide,
            "summary": self.summary,
            "source_path": self.source_path,
            "start_line": self.start_line,
            "end_line": self.end_line,
            "commit_hash": self.commit_hash,
            "metadata": self.metadata,
            "embedding": self.embedding,
        }
        if include_code:
            data["code_text"] = self.code_text
        return data

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "KnowledgeDocument":
        """Deserialize from a dictionary."""
        normalized = dict(data)
        possible_errors = normalized.get("possible_errors")
        if isinstance(possible_errors, list):
            parsed_errors = []
            for error in possible_errors:
                if isinstance(error, str):
                    try:
                        parsed_errors.append(json.loads(error))
                    except json.JSONDecodeError:
                        parsed_errors.append({"message": error})
                else:
                    parsed_errors.append(error)
            normalized["possible_errors"] = parsed_errors
        known = {
            field_name: normalized.get(field_name)
            for field_name in cls.__dataclass_fields__.keys()
            if field_name in normalized
        }
        return cls(**known)


class BaseParser:
    """Base class for source parsers."""

    supported_extensions: List[str] = []

    def can_parse(self, path: Path) -> bool:
        """Return whether this parser handles the file extension."""
        return path.suffix.lower() in self.supported_extensions

    def parse(self, source: SourceFile) -> List[KnowledgeDocument]:
        """Parse a source file."""
        raise NotImplementedError
