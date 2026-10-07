"""Retrieval: index individual requests plus one canonical vector per need; score a need by its best match."""

import numpy as np
import pytest

from app.ai.embeddings import Vectors
from app.ai.retrieval import Hit, NeedIndex


class TableEmbedder:
    """Maps known texts to fixed unit vectors, so every similarity below is hand-computable."""

    model_name, dim = "table", 3

    def __init__(self, table: dict[str, list[float]]) -> None:
        self.table = table

    def embed(self, texts: list[str]) -> Vectors:
        rows = np.array([self.table[t] for t in texts], dtype=np.float32)
        return rows / np.linalg.norm(rows, axis=1, keepdims=True)


@pytest.fixture
def index() -> NeedIndex:
    e = TableEmbedder({
        "q": [1, 0, 0],
        "sso-1": [0.6, 0.8, 0],   # cos with q = 0.6
        "sso-2": [0.9, 0.4359, 0],  # cos 0.9 (normalised: 0.9/1.0 = 0.9)
        "export-1": [0.8, 0, 0.6],  # cos 0.8
        "export-2": [0.8, 0, 0.6],  # cos 0.8 (same as export-1)
        "export-3": [0.8, 0, 0.6],  # cos 0.8
        "dark-canon": [0.7, 0, 0.7141],  # cos 0.7
        "far": [0, 0, 1],  # cos 0
    })  # fmt: skip
    idx = NeedIndex(e)
    idx.add_request("R1", "sso", "sso-1")
    idx.add_request("R2", "sso", "sso-2")
    for i in (1, 2, 3):
        idx.add_request(f"R{i + 2}", "export", f"export-{i}")
    idx.add_canonical("dark", "dark-canon")
    idx.add_request("R9", "far", "far")
    return idx


def test_a_need_scores_its_best_match_not_its_size(index: NeedIndex) -> None:
    hits = index.search("q", k=5)
    # sso: best of 0.6 and 0.9 = 0.9; export: three members at 0.8 still score 0.8
    assert [(h.need_id, round(h.score, 3), h.via) for h in hits] == [
        ("sso", 0.9, "R2"),
        ("export", 0.8, "R3"),
        ("dark", 0.7, "canonical"),
        ("far", 0.0, "R9"),
    ]


def test_returns_at_most_k_needs(index: NeedIndex) -> None:
    assert [h.need_id for h in index.search("q", k=2)] == ["sso", "export"]


def test_the_canonical_vector_alone_makes_a_need_findable(index: NeedIndex) -> None:
    assert Hit("dark", pytest.approx(0.7, abs=1e-3), "canonical") in index.search("q", k=5)  # type: ignore[arg-type]


def test_empty_index_returns_nothing() -> None:
    assert NeedIndex(TableEmbedder({"q": [1, 0, 0]})).search("q") == []


def test_ties_break_by_need_id() -> None:
    e = TableEmbedder({"q": [1, 0], "a": [1, 0], "b": [1, 0]})
    idx = NeedIndex(e)
    idx.add_request("R2", "zeta", "b")
    idx.add_request("R1", "alpha", "a")
    assert [h.need_id for h in idx.search("q")] == ["alpha", "zeta"]
