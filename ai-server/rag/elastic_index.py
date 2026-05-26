from __future__ import annotations

from collections.abc import Sequence

from elasticsearch import Elasticsearch, helpers


def create_client(url: str) -> Elasticsearch:
    return Elasticsearch(url)


def recreate_index(client: Elasticsearch, index_name: str, embedding_dim: int) -> None:
    if client.indices.exists(index=index_name):
        client.indices.delete(index=index_name)

    client.indices.create(
        index=index_name,
        mappings={
            "properties": {
                "chunk_id": {"type": "keyword"},
                "doc_id": {"type": "keyword"},
                "title": {
                    "type": "text",
                    "fields": {"keyword": {"type": "keyword"}},
                },
                "section": {
                    "type": "text",
                    "fields": {"keyword": {"type": "keyword"}},
                },
                "content": {"type": "text"},
                "embedding": {
                    "type": "dense_vector",
                    "dims": embedding_dim,
                    "index": True,
                    "similarity": "cosine",
                },
                "source_file": {"type": "keyword"},
                "business_area": {"type": "keyword"},
                "customer_type": {"type": "keyword"},
                "channel": {"type": "keyword"},
                "version": {"type": "keyword"},
                "effective_date": {"type": "keyword"},
                "permission_level": {"type": "keyword"},
                "is_active": {"type": "boolean"},
            }
        },
    )


def ensure_index(client: Elasticsearch, index_name: str, embedding_dim: int) -> None:
    if not client.indices.exists(index=index_name):
        recreate_index(client, index_name, embedding_dim)


def bulk_index_chunks(
    client: Elasticsearch,
    index_name: str,
    chunks: Sequence[dict[str, object]],
    embeddings: Sequence[list[float]],
) -> None:
    if len(chunks) != len(embeddings):
        raise ValueError("chunks and embeddings must have the same length")

    actions = []
    for chunk, embedding in zip(chunks, embeddings):
        source = {**chunk, "embedding": embedding}
        actions.append(
            {
                "_index": index_name,
                "_id": chunk["chunk_id"],
                "_source": source,
            }
        )

    if actions:
        helpers.bulk(client, actions)
