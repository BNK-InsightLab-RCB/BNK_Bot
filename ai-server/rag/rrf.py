from __future__ import annotations

from collections import defaultdict


def reciprocal_rank_fusion(
    result_sets: list[list[dict[str, object]]],
    rank_constant: int = 60,
    limit: int = 10,
) -> list[dict[str, object]]:
    scores: dict[str, float] = defaultdict(float)
    documents: dict[str, dict[str, object]] = {}

    for results in result_sets:
        for rank, document in enumerate(results, start=1):
            chunk_id = str(document["chunk_id"])
            scores[chunk_id] += 1.0 / (rank_constant + rank)
            documents[chunk_id] = document

    fused = []
    for chunk_id, score in scores.items():
        fused.append({**documents[chunk_id], "rrf_score": score})

    return sorted(fused, key=lambda item: item["rrf_score"], reverse=True)[:limit]

