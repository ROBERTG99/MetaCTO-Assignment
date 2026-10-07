"""Baseline routing on the top similarity: auto at or above T_auto, suggest at or above T_suggest, else new."""

from pathlib import Path

import pytest

from app.ai.baseline import Routed, Thresholds, load_thresholds, route
from app.ai.retrieval import Hit

TH = Thresholds(auto=0.85, suggest=0.70)


@pytest.mark.parametrize(
    ("score", "expected"),
    [
        (0.92, Routed("auto", "sso", 0.92)),
        (0.85, Routed("auto", "sso", 0.85)),  # boundary is inclusive
        (0.8499, Routed("suggest", "sso", 0.8499)),
        (0.70, Routed("suggest", "sso", 0.70)),
        (0.6999, Routed("new", None, 0.6999)),
    ],
)
def test_bands(score: float, expected: Routed) -> None:
    assert route([Hit("sso", score, "R1"), Hit("scim", score - 0.1, "R8")], TH) == expected


def test_no_candidates_is_a_new_need() -> None:
    assert route([], TH) == Routed("new", None, 0.0)


def test_thresholds_load_from_the_routing_config(tmp_path: Path) -> None:
    cfg = tmp_path / "routing.yaml"
    cfg.write_text("baseline:\n  auto: 0.88\n  suggest: 0.71\n  tuned_on: dev\n")
    assert load_thresholds(cfg) == Thresholds(auto=0.88, suggest=0.71)


def test_suggest_above_auto_is_rejected(tmp_path: Path) -> None:
    cfg = tmp_path / "routing.yaml"
    cfg.write_text("baseline:\n  auto: 0.70\n  suggest: 0.80\n")
    with pytest.raises(ValueError, match="suggest"):
        load_thresholds(cfg)
