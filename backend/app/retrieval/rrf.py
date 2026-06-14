"""Reciprocal Rank Fusion."""

from __future__ import annotations

from typing import Dict, Iterable, List, Tuple, TypeVar


T = TypeVar("T")


def reciprocal_rank_fusion(result_lists: Iterable[List[T]], k: int = 60, top_k: int = 10) -> List[Tuple[T, float]]:
    """Fuse ranked result lists using client-side RRF."""
    scores: Dict[str, float] = {}
    items: Dict[str, T] = {}
    for result_list in result_lists:
        for rank, item in enumerate(result_list, start=1):
            item_id = getattr(item, "id", None) or str(item)
            scores[item_id] = scores.get(item_id, 0.0) + 1.0 / (k + rank)
            items[item_id] = item
    ranked = sorted(scores.items(), key=lambda pair: pair[1], reverse=True)
    return [(items[item_id], score) for item_id, score in ranked[:top_k]]
