from dataclasses import dataclass

from backend.app.retrieval.rrf import reciprocal_rank_fusion


@dataclass
class Item:
    id: str


def test_rrf_promotes_items_seen_in_multiple_lists():
    a = Item("a")
    b = Item("b")
    c = Item("c")

    fused = reciprocal_rank_fusion([[a, b], [c, a]], top_k=3)

    assert fused[0][0].id == "a"
    assert len(fused) == 3
