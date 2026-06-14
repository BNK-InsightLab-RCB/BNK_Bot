"""Indexing helper."""

from __future__ import annotations

from typing import Iterable, List

from backend.app.embedding.embedder import Embedder
from backend.app.parsers.base import KnowledgeDocument
from backend.app.storage.elastic import KnowledgeIndex


class Indexer:
    """Embed and persist knowledge documents."""

    def __init__(self, index: KnowledgeIndex, embedder: Embedder) -> None:
        self.index = index
        self.embedder = embedder

    def index_documents(self, docs: Iterable[KnowledgeDocument], reset_index: bool = False) -> List[KnowledgeDocument]:
        """Embed documents and write them to storage."""
        documents = list(docs)
        if reset_index:
            self.index.reset()
        vectors = self.embedder.embed_texts(doc.searchable_text() for doc in documents)
        for doc, vector in zip(documents, vectors):
            doc.embedding = vector
        self.index.index_documents(documents)
        return documents
