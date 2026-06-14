"""End-to-end ingestion pipeline CLI."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from typing import List

from backend.app.config import settings
from backend.app.embedding.embedder import Embedder
from backend.app.ingestion.indexer import Indexer
from backend.app.ingestion.scanner import SourceScanner
from backend.app.ingestion.summarizer import Summarizer
from backend.app.parsers.base import BaseParser, KnowledgeDocument, SourceFile
from backend.app.parsers.frontend_parser import FrontendParser
from backend.app.parsers.java_parser import JavaParser
from backend.app.parsers.mybatis_parser import MyBatisParser
from backend.app.parsers.sql_parser import SqlParser
from backend.app.parsers.table_doc_parser import TableDocParser
from backend.app.storage.elastic import KnowledgeIndex
from backend.app.storage.sqlite import SQLiteGraphStore


@dataclass
class IngestionResult:
    """Ingestion result metadata."""

    indexed_count: int
    docs: List[KnowledgeDocument]


class IngestionPipeline:
    """Scan, parse, summarize, embed, index, and graph source documents."""

    def __init__(
        self,
        index_path: str = "",
        sqlite_path: str = "",
        parsers: List[BaseParser] = None,
    ) -> None:
        self.scanner = SourceScanner()
        self.parsers = parsers or [
            FrontendParser(),
            JavaParser(),
            MyBatisParser(),
            SqlParser(),
            TableDocParser(),
        ]
        self.index = KnowledgeIndex(local_path=index_path or settings.local_index_path)
        self.embedder = Embedder()
        self.indexer = Indexer(self.index, self.embedder)
        self.graph_store = SQLiteGraphStore(sqlite_path or settings.sqlite_path)
        self.summarizer = Summarizer()

    def run(
        self,
        source_dir: str,
        reset_index: bool = False,
        generate_summaries: bool = False,
    ) -> IngestionResult:
        """Run the full ingestion pipeline."""
        source_files = self.scanner.scan(source_dir)
        docs = self._parse(source_files)
        docs = self._link_documents(docs)
        docs = self.summarizer.enrich(docs, use_llm=generate_summaries)
        if reset_index:
            self.graph_store.reset()
        indexed = self.indexer.index_documents(docs, reset_index=reset_index)
        self.graph_store.build_from_documents(indexed)
        return IngestionResult(indexed_count=len(indexed), docs=indexed)

    def _parse(self, source_files: List[SourceFile]) -> List[KnowledgeDocument]:
        docs: List[KnowledgeDocument] = []
        for source in source_files:
            for parser in self.parsers:
                if parser.can_parse(source.path):
                    docs.extend(parser.parse(source))
                    break
        return docs

    def _link_documents(self, docs: List[KnowledgeDocument]) -> List[KnowledgeDocument]:
        api_to_controller = {
            doc.api_path: doc
            for doc in docs
            if doc.doc_type == "backend_controller" and doc.api_path
        }
        mapper_by_method = {
            (doc.sql_id or "").split(".")[-1]: doc for doc in docs if doc.doc_type == "sql_mapper" and doc.sql_id
        }
        for doc in docs:
            if doc.doc_type == "frontend_event" and doc.api_path in api_to_controller:
                controller = api_to_controller[doc.api_path]
                doc.metadata["controller"] = controller.title
            if doc.doc_type == "business_logic":
                related_sql_ids = []
                related_tables = []
                for call in doc.metadata.get("mapper_calls", []):
                    method = str(call).split(".")[-1]
                    mapper_doc = mapper_by_method.get(method)
                    if mapper_doc:
                        related_sql_ids.append(mapper_doc.sql_id)
                        related_tables.extend(mapper_doc.tables)
                doc.metadata["related_sql_ids"] = [value for value in related_sql_ids if value]
                doc.tables = list(dict.fromkeys(doc.tables + related_tables))
        return docs


def main() -> None:
    parser = argparse.ArgumentParser(description="Ingest source-aware ops RAG documents.")
    parser.add_argument("--source-dir", required=True)
    parser.add_argument("--reset-index", action="store_true")
    parser.add_argument("--generate-summaries", action="store_true")
    args = parser.parse_args()
    result = IngestionPipeline().run(
        source_dir=args.source_dir,
        reset_index=args.reset_index,
        generate_summaries=args.generate_summaries,
    )
    print(f"Indexed {result.indexed_count} documents")


if __name__ == "__main__":
    main()
