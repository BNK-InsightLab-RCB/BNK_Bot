from __future__ import annotations

from elasticsearch import Elasticsearch

from rag.embedder import KureEmbedder
from rag.rrf import reciprocal_rank_fusion


class HybridSearcher:
    def __init__(
        self,
        client: Elasticsearch,
        index_name: str,
        embedder: KureEmbedder,
    ) -> None:
        self.client = client
        self.index_name = index_name
        self.embedder = embedder

    def search(self, query: str, bm25_k: int = 20, vector_k: int = 20, top_k: int = 10) -> list[dict[str, object]]:
        bm25_results = self.bm25_search(query, bm25_k)
        vector_results = self.vector_search(query, vector_k)
        return reciprocal_rank_fusion([bm25_results, vector_results], limit=top_k)

    def bm25_search(self, query: str, top_k: int) -> list[dict[str, object]]:
        response = self.client.search(
            index=self.index_name,
            size=top_k,
            query={
                "bool": {
                    "filter": [{"term": {"is_active": True}}],
                    "must": [
                        {
                            "multi_match": {
                                "query": query,
                                "fields": ["title^3", "section^2", "content"],
                                "type": "best_fields",
                            }
                        }
                    ],
                }
            },
        )
        return [_hit_to_result(hit, "bm25") for hit in response["hits"]["hits"]]

    def vector_search(self, query: str, top_k: int) -> list[dict[str, object]]:
        query_vector = self.embedder.encode([query], batch_size=1)[0]
        response = self.client.search(
            index=self.index_name,
            size=top_k,
            query={
                "script_score": {
                    "query": {"bool": {"filter": [{"term": {"is_active": True}}]}},
                    "script": {
                        "source": "cosineSimilarity(params.query_vector, 'embedding') + 1.0",
                        "params": {"query_vector": query_vector},
                    },
                }
            },
        )
        return [_hit_to_result(hit, "vector") for hit in response["hits"]["hits"]]


def _hit_to_result(hit: dict[str, object], search_type: str) -> dict[str, object]:
    source = hit["_source"]
    return {
        "chunk_id": source["chunk_id"],
        "doc_id": source["doc_id"],
        "title": source["title"],
        "section": source["section"],
        "content": source["content"],
        "source_file": source["source_file"],
        "search_type": search_type,
        "raw_score": hit["_score"],
    }

