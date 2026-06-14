"""Business-rule enrichment with static fallback and optional Qwen call."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, List

from backend.app.config import settings
from backend.app.llm.prompts import SOURCE_SUMMARY_PROMPT
from backend.app.llm.qwen_client import QwenClient
from backend.app.parsers.base import KnowledgeDocument
from backend.app.utils.text import strip_code_fence


class Summarizer:
    """Enrich parser output with summaries, business rules, and guides."""

    def __init__(self, checkpoint_path: str = "./data/summary_checkpoint.json") -> None:
        self.checkpoint_path = Path(checkpoint_path)
        self.checkpoint_path.parent.mkdir(parents=True, exist_ok=True)
        self.checkpoint = self._load_checkpoint()
        self.client = QwenClient()

    def enrich(self, docs: List[KnowledgeDocument], use_llm: bool = False) -> List[KnowledgeDocument]:
        """Enrich documents. LLM failures fall back to static parser fields."""
        enriched: List[KnowledgeDocument] = []
        for doc in docs:
            self._static_enrich(doc)
            if use_llm and settings.enable_llm_summary and doc.code_text:
                self._llm_enrich(doc)
            enriched.append(doc)
            self.checkpoint[doc.id or doc.title] = doc.to_dict(include_code=False)
            self._save_checkpoint()
        return enriched

    def _static_enrich(self, doc: KnowledgeDocument) -> None:
        if not doc.summary:
            doc.summary = _fallback_summary(doc)
        if not doc.branch_guide and doc.possible_errors:
            doc.branch_guide = " ".join(
                str(error.get("branch_guide", "")) for error in doc.possible_errors if error
            ).strip()
        if not doc.it_guide:
            identifiers = [
                doc.api_path or "",
                doc.class_name or "",
                doc.method_name or "",
                doc.sql_id or "",
                ", ".join(doc.tables),
            ]
            doc.it_guide = " / ".join(part for part in identifiers if part)

    def _llm_enrich(self, doc: KnowledgeDocument) -> None:
        if doc.id in self.checkpoint:
            return
        prompt = SOURCE_SUMMARY_PROMPT.format(
            source_path=doc.source_path,
            language=doc.doc_type,
            code=doc.code_text[:6000],
        )
        content = self.client.chat(
            [{"role": "user", "content": prompt}],
            temperature=0.0,
            enable_thinking=settings.enable_thinking_for_summary,
        )
        if not content:
            return
        try:
            payload = json.loads(strip_code_fence(content))
        except json.JSONDecodeError:
            return
        doc.summary = payload.get("summary") or doc.summary
        doc.business_rules = doc.business_rules or payload.get("business_rules", [])
        doc.possible_errors = doc.possible_errors or payload.get("possible_errors", [])
        if payload.get("branch_guide") and not doc.branch_guide:
            doc.branch_guide = payload["branch_guide"]
        if payload.get("it_guide") and not doc.it_guide:
            doc.it_guide = payload["it_guide"]

    def _load_checkpoint(self) -> Dict[str, object]:
        if not self.checkpoint_path.exists():
            return {}
        try:
            return json.loads(self.checkpoint_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return {}

    def _save_checkpoint(self) -> None:
        self.checkpoint_path.write_text(
            json.dumps(self.checkpoint, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )


def _fallback_summary(doc: KnowledgeDocument) -> str:
    if doc.doc_type == "frontend_event":
        return f"{doc.screen_name or '화면'}에서 {doc.method_name or doc.title} 이벤트를 처리한다."
    if doc.doc_type == "backend_controller":
        return f"{doc.class_name}.{doc.method_name}가 {doc.api_path or '요청'}을 처리한다."
    if doc.doc_type == "business_logic":
        return f"{doc.class_name}.{doc.method_name} 업무 규칙을 검증한다."
    if doc.doc_type == "sql_mapper":
        return f"{doc.sql_id or doc.title} SQL이 {', '.join(doc.tables)} 테이블을 사용한다."
    return doc.title
