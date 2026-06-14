"""Hybrid search over Elasticsearch or the local JSON fallback index."""

from __future__ import annotations

import math
import re
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

from backend.app.config import settings
from backend.app.embedding.embedder import Embedder
from backend.app.parsers.base import KnowledgeDocument
from backend.app.retrieval.query_analyzer import QueryIntent
from backend.app.retrieval.rrf import reciprocal_rank_fusion
from backend.app.storage.elastic import KnowledgeIndex


class HybridSearcher:
    """Search exact metadata, lexical text, and vectors, then fuse results."""

    def __init__(
        self,
        index: Optional[KnowledgeIndex] = None,
        embedder: Optional[Embedder] = None,
        use_elasticsearch: Optional[bool] = None,
    ) -> None:
        self.index = index or KnowledgeIndex()
        self.embedder = embedder or Embedder()
        if use_elasticsearch is None:
            use_elasticsearch = (
                settings.use_elasticsearch_search
                and Path(self.index.local_path) == Path(settings.local_index_path)
            )
        self.use_elasticsearch = use_elasticsearch

    def search(
        self,
        intent: QueryIntent,
        user_role: str = "branch",
        filters: Optional[Dict[str, object]] = None,
        top_k: int = 10,
    ) -> List[Tuple[KnowledgeDocument, float]]:
        """Run hybrid search."""
        if self.use_elasticsearch:
            elastic_results = self._search_elasticsearch(intent, filters or {}, top_k)
            if elastic_results:
                return elastic_results
        docs = self.index.load_documents()
        docs = _apply_filters(docs, filters or {})
        exact = self._exact(intent, docs)
        lexical = self._bm25_like(intent, docs)
        vector = self._vector(intent.query, docs)
        anchored_ids = {doc.id for doc in exact + lexical}
        if anchored_ids:
            vector = [
                doc
                for doc in vector
                if doc.id in anchored_ids or _shares_anchor(intent, doc, exact + lexical)
            ]
        fused = reciprocal_rank_fusion([exact, lexical, vector], top_k=top_k)
        if intent.action:
            fused = sorted(
                fused,
                key=lambda pair: pair[1]
                + (0.05 if intent.action in pair[0].searchable_text() else 0.0),
                reverse=True,
            )
        fused = _prefer_screen_context(fused, intent)
        return fused[:top_k]

    def _search_elasticsearch(
        self,
        intent: QueryIntent,
        filters: Dict[str, object],
        top_k: int,
    ) -> List[Tuple[KnowledgeDocument, float]]:
        client = self.index.client()
        if client is None:
            return []
        try:
            if not client.indices.exists(index=self.index.index_name):
                return []
            exact = self._elastic_exact(client, intent, filters, top_k)
            bm25 = self._elastic_bm25(client, intent, filters, top_k)
            vector = self._elastic_vector(client, intent, filters, top_k)
        except Exception:
            return []
        anchored_ids = {doc.id for doc in exact + bm25}
        if anchored_ids:
            vector = [
                doc
                for doc in vector
                if doc.id in anchored_ids or _shares_anchor(intent, doc, exact + bm25)
            ]
        fused = reciprocal_rank_fusion([exact, bm25, vector], top_k=top_k)
        if intent.action:
            fused = sorted(
                fused,
                key=lambda pair: pair[1]
                + (0.05 if intent.action in pair[0].searchable_text() else 0.0),
                reverse=True,
            )
        fused = _prefer_screen_context(fused, intent)
        return [(doc, score) for doc, score in fused[:top_k]]

    def _elastic_exact(
        self,
        client: object,
        intent: QueryIntent,
        filters: Dict[str, object],
        top_k: int,
    ) -> List[KnowledgeDocument]:
        should = []
        if intent.screen_id:
            should.append({"term": {"screen_id": {"value": intent.screen_id, "boost": 10}}})
        if intent.screen_name:
            should.append({"match": {"screen_name": {"query": intent.screen_name, "boost": 8}}})
        if intent.api_path:
            should.append({"term": {"api_path": {"value": intent.api_path, "boost": 10}}})
        if intent.action:
            should.append(
                {
                    "multi_match": {
                        "query": intent.action,
                        "fields": ["summary^3", "business_rules^2", "branch_guide", "it_guide"],
                    }
                }
            )
        if intent.error_message:
            should.append(
                {
                    "multi_match": {
                        "query": intent.error_message,
                        "fields": ["error_messages^4", "possible_errors^3", "business_rules^2", "summary"],
                    }
                }
            )
        if not should:
            should.append({"multi_match": {"query": intent.query, "fields": _bm25_fields()}})
        query = {
            "bool": {
                "should": should,
                "minimum_should_match": 1,
                "filter": _elastic_filters(filters),
            }
        }
        return self._elastic_search(client, query, top_k)

    def _elastic_bm25(
        self,
        client: object,
        intent: QueryIntent,
        filters: Dict[str, object],
        top_k: int,
    ) -> List[KnowledgeDocument]:
        query_text = " ".join(intent.keywords) or intent.query
        query = {
            "bool": {
                "must": [
                    {
                        "multi_match": {
                            "query": query_text,
                            "fields": _bm25_fields(),
                            "type": "best_fields",
                            "operator": "or",
                        }
                    }
                ],
                "filter": _elastic_filters(filters),
            }
        }
        return self._elastic_search(client, query, top_k)

    def _elastic_vector(
        self,
        client: object,
        intent: QueryIntent,
        filters: Dict[str, object],
        top_k: int,
    ) -> List[KnowledgeDocument]:
        query_vector = self.embedder.embed_text(intent.query)
        base_query: Dict[str, object] = {"match_all": {}}
        elastic_filters = _elastic_filters(filters)
        if elastic_filters:
            base_query = {"bool": {"filter": elastic_filters}}
        query = {
            "script_score": {
                "query": base_query,
                "script": {
                    "source": "cosineSimilarity(params.query_vector, 'embedding') + 1.0",
                    "params": {"query_vector": query_vector},
                },
            }
        }
        return self._elastic_search(client, query, top_k)

    def _elastic_search(
        self,
        client: object,
        query: Dict[str, object],
        top_k: int,
    ) -> List[KnowledgeDocument]:
        response = client.search(
            index=self.index.index_name,
            query=query,
            size=top_k,
            source=True,
        )
        hits = response.body.get("hits", {}).get("hits", [])
        docs: List[KnowledgeDocument] = []
        for hit in hits:
            source = hit.get("_source") or {}
            source.setdefault("id", hit.get("_id"))
            doc = KnowledgeDocument.from_dict(source)
            doc.metadata["retrieval_backend"] = "elasticsearch"
            doc.metadata["elastic_score"] = hit.get("_score")
            docs.append(doc)
        return docs

    def _exact(self, intent: QueryIntent, docs: Iterable[KnowledgeDocument]) -> List[KnowledgeDocument]:
        scored: List[Tuple[KnowledgeDocument, int]] = []
        for doc in docs:
            score = 0
            if intent.screen_id and doc.screen_id == intent.screen_id:
                score += 10
            if intent.screen_name and doc.screen_name and intent.screen_name in doc.screen_name:
                score += 8
            if intent.api_path and doc.api_path == intent.api_path:
                score += 10
            if intent.action:
                joined = doc.searchable_text()
                if intent.action in joined:
                    score += 4
            if intent.error_message:
                joined_errors = " ".join(doc.error_messages + doc.business_rules)
                if intent.error_message in joined_errors or intent.error_message in doc.summary:
                    score += 5
            if score:
                scored.append((doc, score))
        return [doc for doc, _ in sorted(scored, key=lambda pair: pair[1], reverse=True)]

    def _bm25_like(self, intent: QueryIntent, docs: Iterable[KnowledgeDocument]) -> List[KnowledgeDocument]:
        query_terms = _terms(" ".join(intent.keywords) or intent.query)
        scored: List[Tuple[KnowledgeDocument, float]] = []
        for doc in docs:
            text = doc.searchable_text().lower()
            terms = _terms(text)
            if not terms:
                continue
            term_counts = {term: terms.count(term) for term in set(terms)}
            score = 0.0
            for term in query_terms:
                if term in text:
                    score += 1.5
                score += term_counts.get(term, 0) / math.sqrt(len(terms))
            if score:
                scored.append((doc, score))
        return [doc for doc, _ in sorted(scored, key=lambda pair: pair[1], reverse=True)]

    def _vector(self, query: str, docs: Iterable[KnowledgeDocument]) -> List[KnowledgeDocument]:
        query_vector = self.embedder.embed_text(query)
        scored: List[Tuple[KnowledgeDocument, float]] = []
        for doc in docs:
            if not doc.embedding:
                continue
            score = _cosine(query_vector, doc.embedding)
            if score > 0:
                scored.append((doc, score))
        return [doc for doc, _ in sorted(scored, key=lambda pair: pair[1], reverse=True)]


def _apply_filters(docs: List[KnowledgeDocument], filters: Dict[str, object]) -> List[KnowledgeDocument]:
    if not filters:
        return docs
    result = []
    for doc in docs:
        keep = True
        for key, value in filters.items():
            if value is None:
                continue
            doc_value = getattr(doc, key, None)
            if isinstance(value, list):
                keep = doc_value in value or bool(set(value) & set(doc_value if isinstance(doc_value, list) else []))
            else:
                keep = doc_value == value
            if not keep:
                break
        if keep:
            result.append(doc)
    return result


def _shares_anchor(intent: QueryIntent, doc: KnowledgeDocument, anchors: List[KnowledgeDocument]) -> bool:
    if intent.screen_name and doc.screen_name and doc.screen_name != intent.screen_name:
        return False
    doc_values = _doc_anchor_values(doc)
    if not doc_values:
        return False
    for anchor in anchors:
        if doc_values & _doc_anchor_values(anchor):
            return True
    return False


def _prefer_screen_context(
    ranked: List[Tuple[KnowledgeDocument, float]],
    intent: QueryIntent,
) -> List[Tuple[KnowledgeDocument, float]]:
    """When a screen is explicit, avoid mixing generic same-action documents."""
    if not intent.screen_name:
        return ranked
    focused = [pair for pair in ranked if _matches_screen_context(pair[0], intent)]
    if len(focused) >= 2:
        focus_docs = [doc for doc, _ in focused]
        related = [
            pair
            for pair in ranked
            if pair not in focused and _shares_screen_anchor(pair[0], focus_docs)
        ]
        return focused + related
    return ranked


def _matches_screen_context(doc: KnowledgeDocument, intent: QueryIntent) -> bool:
    if intent.screen_id and doc.screen_id == intent.screen_id:
        return True
    if intent.screen_name and doc.screen_name == intent.screen_name:
        return True
    text = doc.searchable_text()
    if intent.screen_name and intent.screen_name in text:
        return True
    return False


def _shares_screen_anchor(doc: KnowledgeDocument, anchors: List[KnowledgeDocument]) -> bool:
    doc_values = _doc_screen_anchor_values(doc)
    if not doc_values:
        return False
    return any(doc_values & _doc_screen_anchor_values(anchor) for anchor in anchors)


def _doc_screen_anchor_values(doc: KnowledgeDocument) -> set:
    values = {
        doc.screen_id,
        doc.screen_name,
        doc.api_path,
        doc.method_name,
        doc.sql_id,
    }
    values |= set(doc.metadata.get("mapper_calls", []))
    values |= set(doc.metadata.get("service_calls", []))
    values |= set(doc.metadata.get("related_sql_ids", []))
    return {value for value in values if value}


def _doc_anchor_values(doc: KnowledgeDocument) -> set:
    values = {
        doc.screen_id,
        doc.screen_name,
        doc.api_path,
        doc.sql_id,
        doc.class_name,
        doc.method_name,
    }
    values |= set(doc.tables)
    values |= set(doc.metadata.get("mapper_calls", []))
    values |= set(doc.metadata.get("service_calls", []))
    values |= set(doc.metadata.get("related_sql_ids", []))
    return {value for value in values if value}


def _terms(text: str) -> List[str]:
    return [token.lower() for token in re.findall(r"[A-Za-z0-9_]+|[가-힣]{2,}", text)]


def _bm25_fields() -> List[str]:
    return [
        "title^4",
        "screen_name^4",
        "error_messages^4",
        "summary^3",
        "business_rules^3",
        "possible_errors^3",
        "branch_guide^2",
        "it_guide^2",
        "code_text",
    ]


def _elastic_filters(filters: Dict[str, object]) -> List[Dict[str, object]]:
    clauses: List[Dict[str, object]] = []
    for key, value in filters.items():
        if value is None:
            continue
        if isinstance(value, list):
            clauses.append({"terms": {key: value}})
        else:
            clauses.append({"term": {key: value}})
    return clauses


def _cosine(left: List[float], right: List[float]) -> float:
    if not left or not right:
        return 0.0
    size = min(len(left), len(right))
    dot = sum(left[index] * right[index] for index in range(size))
    left_norm = math.sqrt(sum(value * value for value in left[:size])) or 1.0
    right_norm = math.sqrt(sum(value * value for value in right[:size])) or 1.0
    return dot / (left_norm * right_norm)
