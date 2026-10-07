"""Metric tests. Every expected value is computed by hand in the comments, not by the code under test."""

import pytest

from evals.metrics import (
    Decision,
    Rate,
    accuracy_by_bucket,
    decision_accuracy,
    duplicate_prf,
    false_merge_rate,
    percentile,
    recall_at_k,
    wilson,
)

# Eight decisions covering every outcome. None = new need.
#  #  expected predicted  score  candidates            outcome
#  1  A        A          0.95   A B C                 right link (TP)
#  2  A        B          0.91   B A C                 wrong need (false merge, missed dup)
#  3  None     None       0.40   -                     right "new"
#  4  None     A          0.72   A                     linked when it should be new (false merge)
#  5  B        None       0.55   C D E F B             missed duplicate
#  6  B        B          0.88   B C                   right link (TP)
#  7  C        C          0.99   A B D E F C           right link (TP)
#  8  None     None       0.10   -                     right "new"
D = [
    Decision("A", "A", 0.95, "auto", ("A", "B", "C")),
    Decision("A", "B", 0.91, "auto", ("B", "A", "C")),
    Decision(None, None, 0.40, "new"),
    Decision(None, "A", 0.72, "suggest", ("A",)),
    Decision("B", None, 0.55, "new", ("C", "D", "E", "F", "B")),
    Decision("B", "B", 0.88, "auto", ("B", "C")),
    Decision("C", "C", 0.99, "auto", ("A", "B", "D", "E", "F", "C")),
    Decision(None, None, 0.10, "new"),
]


def test_decision_accuracy_counts_right_links_and_right_news() -> None:
    # right: 1, 3, 6, 7, 8 -> 5 of 8
    assert decision_accuracy(D) == Rate(5, 8)
    assert decision_accuracy(D).value == pytest.approx(0.625)


def test_duplicate_precision_recall_f1() -> None:
    # linked (predicted not None): 1, 2, 4, 6, 7 = 5; true positives 1, 6, 7 = 3 -> precision 3/5
    # duplicates (expected not None): 1, 2, 5, 6, 7 = 5; found 3 -> recall 3/5; F1 = 0.6
    prf = duplicate_prf(D)
    assert (prf.precision, prf.recall) == (Rate(3, 5), Rate(3, 5))
    assert prf.f1 == pytest.approx(0.6)


def test_false_merge_rate_counts_wrong_need_and_link_when_new() -> None:
    # of 5 links, #2 went to the wrong need and #4 should have been new -> 2/5
    assert false_merge_rate(D) == Rate(2, 5)
    assert false_merge_rate(D).value == pytest.approx(0.4)


def test_recall_at_k_only_counts_cases_with_an_existing_need() -> None:
    # cases with an expected need: 1, 2, 5, 6, 7
    # @1: 1, 6        -> 2/5
    # @3: 1, 2, 6     -> 3/5
    # @5: 1, 2, 5, 6  -> 4/5 (7 has C only at rank 6)
    assert [recall_at_k(D, k) for k in (1, 3, 5)] == [Rate(2, 5), Rate(3, 5), Rate(4, 5)]


def test_accuracy_by_bucket() -> None:
    # [0, 0.5):   #3 0.40 right, #8 0.10 right               -> 2/2
    # [0.5, 0.8): #4 0.72 wrong, #5 0.55 wrong               -> 0/2
    # [0.8, 1.0]: #1 right, #2 wrong, #6 right, #7 right     -> 3/4 (the last bucket includes 1.0)
    assert accuracy_by_bucket(D, [0.0, 0.5, 0.8, 1.0]) == [
        (0.0, 0.5, Rate(2, 2)),
        (0.5, 0.8, Rate(0, 2)),
        (0.8, 1.0, Rate(3, 4)),
    ]
    edge = [Decision("A", "A", 1.0), Decision("A", "A", 0.8)]
    assert accuracy_by_bucket(edge, [0.0, 0.8, 1.0]) == [(0.0, 0.8, Rate(0, 0)), (0.8, 1.0, Rate(2, 2))]


@pytest.mark.parametrize(
    ("k", "n", "lo", "hi"),
    [
        (3, 5, 0.2307, 0.8824),
        (0, 10, 0.0, 0.2775),
        (10, 10, 0.7225, 1.0),
        (70, 75, 0.8532, 0.9712),
    ],
)
def test_wilson_95_interval(k: int, n: int, lo: float, hi: float) -> None:
    # p=k/n, d=1+z²/n, center=(p+z²/2n)/d, half=z·sqrt(p(1-p)/n+z²/4n²)/d, z=1.96
    assert wilson(k, n) == pytest.approx((lo, hi), abs=1e-4)
    assert Rate(k, n).interval == pytest.approx((lo, hi), abs=1e-4)


def test_empty_rate_has_no_value_and_the_widest_interval() -> None:
    assert Rate(0, 0).value is None
    assert Rate(0, 0).interval == (0.0, 1.0)
    assert duplicate_prf([Decision(None, None)]).f1 is None


def test_percentile_uses_nearest_rank() -> None:
    values = [float(v) for v in range(100, 0, -10)]  # 10..100, unsorted on purpose
    # nearest rank = ceil(q * n): p50 -> 5th = 50, p90 -> 9th = 90, p95 -> ceil(9.5) = 10th = 100
    assert [percentile(values, q) for q in (0.5, 0.9, 0.95)] == [50.0, 90.0, 100.0]
    assert percentile([30.0, 10.0, 20.0], 0.5) == 20.0  # ceil(1.5) = 2nd
    assert percentile([7.0], 0.95) == 7.0
    with pytest.raises(ValueError):
        percentile([], 0.5)


def test_scores_outside_the_edges_land_in_the_end_buckets() -> None:
    # float32 dot products of identical vectors can give 1.0000001; nothing may fall out of the table
    ds = [Decision("A", "A", 1.0000001), Decision(None, None, -0.01)]
    assert accuracy_by_bucket(ds, [0.0, 0.5, 1.0]) == [(0.0, 0.5, Rate(1, 1)), (0.5, 1.0, Rate(1, 1))]
