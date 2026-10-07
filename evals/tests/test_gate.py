"""The CI eval gate: the free offline baseline must not regress below the committed floors."""

from evals.gate import regressions

RESULT = {"overall": {"accuracy": {"value": 0.71}, "dup_recall": {"value": 0.81},
                      "false_merge_auto": {"value": 0.10}}}  # fmt: skip


def test_a_result_at_or_above_every_floor_passes() -> None:
    floors = {"accuracy": {"min": 0.70}, "dup_recall": {"min": 0.80}, "false_merge_auto": {"max": 0.12}}
    assert regressions(RESULT, floors) == []


def test_each_regression_is_named() -> None:
    floors = {"accuracy": {"min": 0.72}, "dup_recall": {"min": 0.80}, "false_merge_auto": {"max": 0.05}}
    assert regressions(RESULT, floors) == [
        "accuracy 0.7100 is below the floor 0.7200",
        "false_merge_auto 0.1000 is above the ceiling 0.0500",
    ]


def test_a_missing_metric_is_a_regression() -> None:
    assert regressions({"overall": {}}, {"accuracy": {"min": 0.5}}) == ["accuracy is missing from the result"]
