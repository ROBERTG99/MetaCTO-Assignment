"""Threshold choice on dev. Decisions carry the top candidate as `predicted` and its similarity as `score`."""

from evals.metrics import Decision
from evals.tune import choose_auto, choose_suggest


def top(expected: str | None, top_need: str, score: float) -> Decision:
    return Decision(expected=expected, predicted=top_need, score=score)


def test_auto_is_the_lowest_threshold_that_keeps_precision_and_volume() -> None:
    # 10 right at 0.90..0.99, one wrong at 0.88, three right at 0.86..0.87
    ds = [top("A", "A", 0.90 + i / 100) for i in range(10)] + [top("A", "B", 0.88)]
    ds += [top("A", "A", s) for s in (0.87, 0.865, 0.86)]
    # T=0.90: 10/10 ok. T=0.88: 10/11 = 0.909 < 0.97. T=0.86: 13/14 = 0.929 < 0.97 -> lowest valid is 0.90
    assert choose_auto(ds, min_precision=0.97, min_links=10) == 0.90


def test_auto_is_none_when_no_threshold_reaches_the_bar() -> None:
    ds = [top("A", "A", 0.95), top(None, "A", 0.94)] + [top("A", "A", 0.9)] * 3
    # never 10 links at >= 97% precision
    assert choose_auto(ds, min_precision=0.97, min_links=10) is None


def test_suggest_keeps_95_percent_of_the_remaining_duplicates() -> None:
    # 20 true duplicates below auto (0.90) at scores 0.50, 0.51, ..., 0.69; plus new requests that don't count
    ds = [top("A", "A", 0.50 + i / 100) for i in range(20)] + [top(None, "B", 0.80), top("A", "A", 0.95)]
    # keep >= 95% of 20 = 19 -> the highest threshold with 19 at or above it is the 2nd lowest score, 0.51
    assert choose_suggest(ds, auto=0.90, keep=0.95) == 0.51


def test_suggest_without_auto_uses_every_duplicate() -> None:
    ds = [top("A", "A", s) for s in (0.2, 0.4, 0.6, 0.8)]
    # keep 95% of 4 = 3.8 -> need all 4 -> 0.2
    assert choose_suggest(ds, auto=None, keep=0.95) == 0.2


def test_chosen_thresholds_keep_the_boundary_decision() -> None:
    """The configured thresholds must reproduce the rule exactly: no rounding past an observed score."""
    from app.ai.baseline import Thresholds, route
    from app.ai.retrieval import Hit

    from evals.tune import choose_thresholds

    ds = [top("A", "A", 0.7665919)] + [top("A", "A", 0.80 + i / 100) for i in range(9)]
    # 0.70 and 0.72 point at the wrong need: at T=0.72 precision is 10/11 = 0.909, so 0.7665919 is the lowest valid
    ds += [top("A", "A", 0.6508366), top("A", "B", 0.70), top("A", "B", 0.72), top(None, "B", 0.60)]
    # suggest: duplicates below auto are 0.6508366, 0.70, 0.72; keeping 95% of 3 needs all 3 -> 0.6508366
    th = choose_thresholds(ds, min_links=10)
    assert th == Thresholds(auto=0.7665919, suggest=0.6508366)
    assert route([Hit("A", 0.7665919, "R1")], th).band == "auto"
    assert route([Hit("A", 0.6508366, "R1")], th).band == "suggest"


def test_no_valid_auto_threshold_means_never_auto_link() -> None:
    from evals.tune import choose_thresholds

    th = choose_thresholds([top(None, "A", 0.95), top("A", "A", 0.6)], min_links=10)
    assert th.auto > 1.0 and th.suggest == 0.6
