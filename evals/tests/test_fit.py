"""Strategic-fit eval: agreement metrics, the label check, the no-LLM baselines, and cache-only runs."""

import json
from collections.abc import Mapping
from pathlib import Path

import pytest
from app.ai.embeddings import FakeEmbedder

import evals.fit as fit
from evals.fit import agreement, load_fit_cases, rank_buckets, spearman

GOALS = ("enterprise_readiness", "retention", "self_serve_growth")


def test_agreement_within_one_point_exact_and_mean_absolute_error() -> None:
    a = agreement([(0, 0), (1, 3), (2, 1), (3, 2)])  # (human, model)
    assert (a.within_one.k, a.within_one.n, a.exact.k) == (3, 4, 1)
    assert a.mae == pytest.approx(1.0)
    low, high = a.within_one.interval
    assert low < 0.75 < high  # Wilson interval around 3/4


def test_spearman_ranks_with_ties_averaged() -> None:
    assert spearman([1, 2, 3, 4], [10, 20, 30, 40]) == pytest.approx(1.0)
    assert spearman([1, 2, 3, 4], [4, 3, 2, 1]) == pytest.approx(-1.0)
    assert spearman([1, 1, 2], [1, 2, 3]) == pytest.approx(0.866025, abs=1e-6)
    assert spearman([1, 1, 1], [1, 2, 3]) is None  # no variance: undefined, not 0


def case(i: int, expected: Mapping[str, int | None], reviewed: bool = True) -> dict[str, object]:
    return {"id": f"F{i:02d}", "need": {"title": f"need {i}", "problem": "p", "persona": "it_admin",
            "job_to_be_done": "j"}, "requests": ["text"], "expected": expected, "rationale": "",
            "author": "robert", "reviewed_by_human": reviewed}  # fmt: skip


def write(tmp_path: Path, rows: list[dict[str, object]]) -> Path:
    path = tmp_path / "strategic_fit.jsonl"
    path.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    return path


def test_cases_must_be_rated_and_reviewed_by_a_human_before_the_eval_runs(tmp_path: Path) -> None:
    full = dict.fromkeys(GOALS, 2)
    path = write(
        tmp_path, [case(1, full), case(2, {**full, "retention": None}), case(3, full, reviewed=False)]
    )
    with pytest.raises(ValueError, match="F02, F03"):
        load_fit_cases(path, GOALS)
    assert len(load_fit_cases(path, GOALS, require_labels=False)) == 3


@pytest.mark.parametrize(
    "expected",
    [{"enterprise_readiness": 4, "retention": 0, "self_serve_growth": 0},
     {"enterprise_readiness": 1, "retention": 0},
     {"enterprise_readiness": 1, "retention": 0, "self_serve_growth": 0, "world_peace": 3}],
    ids=["out-of-range", "missing-goal", "unknown-goal"],
)  # fmt: skip
def test_malformed_labels_are_refused(tmp_path: Path, expected: dict[str, int]) -> None:
    with pytest.raises(ValueError):
        load_fit_cases(write(tmp_path, [case(1, expected)]), GOALS)


def test_rank_buckets_spread_scores_over_0_to_3_by_rank() -> None:
    assert rank_buckets({"a": 0.1, "b": 0.4, "c": 0.3, "d": 0.9}) == {"a": 0, "c": 1, "b": 2, "d": 3}
    ten = rank_buckets({f"n{i}": float(i) for i in range(10)})
    assert [ten[f"n{i}"] for i in range(10)] == [0, 0, 0, 1, 1, 2, 2, 2, 3, 3]


def test_a_free_run_with_an_empty_cache_reports_misses_and_writes_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(fit, "CACHE", tmp_path / "fit_cache.jsonl")
    monkeypatch.setattr(fit, "SEED_OUT", tmp_path / "fit_snapshot.json")
    monkeypatch.setattr(fit, "RESULT_MD", tmp_path / "strategic_fit.md")
    monkeypatch.setattr(fit, "FastEmbedder", lambda **_k: FakeEmbedder())
    assert fit.main([]) == 2
    assert not (tmp_path / "fit_snapshot.json").exists() and not (tmp_path / "strategic_fit.md").exists()
    assert not (tmp_path / "fit_cache.jsonl").exists() or (tmp_path / "fit_cache.jsonl").read_text() == ""


def test_a_paid_run_is_refused_outside_make_eval(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("EVAL_ALLOW_PAID", raising=False)
    assert fit.main(["--paid"]) == 2


def test_a_paid_run_is_refused_until_every_case_is_labelled(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("EVAL_ALLOW_PAID", "1")
    monkeypatch.setattr(fit, "DATASET", write(tmp_path, [case(1, dict.fromkeys(GOALS, None))]))

    def no_calls(*_a: object, **_k: object) -> None:
        raise AssertionError("no rating may run before the labels exist")

    monkeypatch.setattr(fit, "rate_all", no_calls)
    monkeypatch.setattr(fit, "seeded_needs", no_calls)
    assert fit.main(["--paid"]) == 2


def test_a_failed_rating_counts_as_a_miss_for_the_model_only(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.ai.schemas import FitRating, StrategicFit
    from app.scoring import PrioritiesConfig

    cases = [fit.FitCase.model_validate(case(i, dict.fromkeys(GOALS, 1))) for i in (1, 2)]
    out = StrategicFit(ratings=[FitRating(goal=g, rating=1, rationale="r", quote="") for g in GOALS])
    rated = {"case:F01": fit.Rated(out, [], 1000.0)}
    md = fit.report(cases, rated, {"case:F02": "refused"}, PrioritiesConfig(), FakeEmbedder())
    haiku = next(line for line in md.splitlines() if line.startswith("| Haiku"))
    constant = next(line for line in md.splitlines() if line.startswith("| Constant 1"))
    assert (
        "3/6" in haiku and "6/6" in constant
    )  # F02 costs the model 3 pairs; the baselines are scored on both
    assert "F02 (refused)" in md
