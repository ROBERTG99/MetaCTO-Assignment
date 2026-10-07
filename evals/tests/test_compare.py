"""Comparison scoring: a provider failure is a wrong decision but never a link; the cascade's cost and latency."""

import pytest

from evals.compare import cascade_rows, summarize


def row(ref: str, expected: str | None, predicted: str | None, band: str, cost: float = 0.01, lat: float = 100.0,
        ext_cost: float = 0.003, ext_lat: float = 40.0) -> dict[str, object]:  # fmt: skip
    return {"ref": ref, "expected": expected, "predicted": predicted, "band": band, "score": 0.9, "candidates": [],
            "latency_ms": lat, "cost": cost, "extract_cost": ext_cost, "extract_latency_ms": ext_lat, "tags": []}  # fmt: skip


def test_a_failure_is_wrong_but_not_a_link() -> None:
    m = summarize([row("A", None, None, "failed"), row("B", "x", "x", "auto")])
    assert (m["accuracy"].k, m["accuracy"].n) == (1, 2)  # the failed "new" isn't right
    assert (m["precision"].k, m["precision"].n) == (1, 1)  # and isn't a link either
    assert m["bands"]["failed"] == 1


def test_the_cascade_pays_haiku_and_only_sonnets_adjudication_when_it_escalates() -> None:
    haiku = {
        "A": row("A", "x", "y", "suggest", cost=0.006, lat=100.0),
        "B": row("B", "x", "x", "auto", cost=0.006),
    }
    sonnet = {
        "A": row("A", "x", "x", "auto", cost=0.011, lat=90.0),
        "B": row("B", "x", None, "new", cost=0.011),
    }
    out = {r["ref"]: r for r in cascade_rows(haiku, sonnet)}
    assert out["A"]["predicted"] == "x" and out["B"]["predicted"] == "x"  # A escalated, B kept
    assert out["A"]["cost"] == pytest.approx(0.006 + (0.011 - 0.003))
    assert out["A"]["latency_ms"] == pytest.approx(100.0 + (90.0 - 40.0))
    assert out["B"]["cost"] == pytest.approx(0.006)
