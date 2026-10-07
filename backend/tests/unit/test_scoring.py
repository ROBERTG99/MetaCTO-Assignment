"""Prioritization math (spec §8, ADR 0009): pure functions, every component returned, hand-computed values."""

from dataclasses import replace
from datetime import date, timedelta
from pathlib import Path

import pytest

from app.scoring import (
    AccountIn,
    PrioritiesConfig,
    breakdown,
    demand,
    fit_due,
    load_priorities,
    owner_for,
    priority,
    quadrant,
    rank_key,
    strategic_fit,
    urgency,
)

TODAY = date(2026, 10, 7)
CFG = (
    PrioritiesConfig()
)  # weights D 0.4, S 0.4, U 0.2; segments ent 1.0, mid 0.9, smb 0.8; p_win 0.2; R_cap $5M
CONFIG = Path(__file__).resolve().parents[3] / "config" / "priorities.yaml"


def acct(i: int, segment: str = "enterprise", arr: int | None = 100_000, **kw: object) -> AccountIn:
    return AccountIn(id=i, name=f"A{i}", segment=segment, arr=arr, **kw)  # type: ignore[arg-type]


def prospect(i: int, pipeline: int | None, segment: str = "enterprise") -> AccountIn:
    return AccountIn(id=i, name=f"P{i}", segment=segment, arr=0, is_prospect=True, pipeline_value=pipeline)


# --- demand ---------------------------------------------------------------------------------------------


def test_demand_is_log_scaled_segment_weighted_arr_plus_prospect_pipeline() -> None:
    d = demand([acct(1), prospect(2, 200_000), acct(3, "mid_market", 60_000), acct(1)], CFG)
    # R = 100k x 1.0 + 0.2 x 200k x 1.0 + 60k x 0.9 = 194k (account 1 counted once)
    # D = log10(1 + 194) / log10(1 + 5000) = 0.619086
    assert d.revenue == pytest.approx(194_000)
    assert d.customer_revenue == pytest.approx(154_000)
    assert d.prospect_revenue == pytest.approx(40_000)
    assert d.value == pytest.approx(0.619086, abs=1e-6)
    assert (d.accounts, d.customers, d.prospects, d.gaps) == (3, 2, 1, ())


def test_no_supporters_means_no_demand() -> None:
    d = demand([], CFG)
    assert (d.value, d.revenue, d.accounts) == (0.0, 0.0, 0)


def test_prospect_only_demand_counts_the_weighted_pipeline() -> None:
    d = demand([prospect(1, 300_000)], CFG)  # 0.2 x 300k = 60k -> log10(61) / log10(5001) = 0.482645
    assert d.value == pytest.approx(0.482645, abs=1e-6)
    assert (d.customers, d.prospects, d.customer_revenue) == (0, 1, 0.0)


def test_missing_arr_or_pipeline_counts_the_account_scores_zero_revenue_and_flags_the_gap() -> None:
    d = demand([acct(1, arr=None), acct(2, arr=0), prospect(3, None)], CFG)
    assert (d.value, d.accounts) == (0.0, 3)
    assert d.gaps == ("A1: no ARR on record", "A2: no ARR on record", "P3: no pipeline value on record")


def test_a_single_huge_account_saturates_instead_of_dominating() -> None:
    huge = demand([acct(1, arr=50_000_000)], CFG)
    assert huge.value == 1.0  # capped at R_cap
    ten_x = demand([acct(1, arr=5_000_000)], CFG).value / demand([acct(1, arr=500_000)], CFG).value
    assert ten_x == pytest.approx(1.3701, abs=1e-4)  # ten times the revenue, 1.37 times the demand


def test_segment_weights_come_from_config() -> None:
    smb_heavy = replace(CFG, segment_weights={"enterprise": 1.0, "mid_market": 1.0, "smb": 2.0})
    assert demand([acct(1, "smb", 50_000)], smb_heavy).revenue == pytest.approx(100_000)


# --- urgency --------------------------------------------------------------------------------------------


def test_urgency_is_the_highest_severity_plus_a_renewal_within_90_days() -> None:
    soon = acct(1, renewal_date=TODAY + timedelta(days=30))
    u = urgency(["nice_to_have", "blocker", None, "important"], [soon, acct(2)], TODAY, CFG)
    assert (u.max_severity, u.severity_score, u.renewal_soon) == ("blocker", 1.0, True)
    assert u.renewing_accounts == ("A1",)
    assert u.value == pytest.approx(0.6 * 1.0 + 0.4 * 1)


@pytest.mark.parametrize(
    ("days", "soon"),
    [(0, True), (90, True), (91, False), (-1, False)],
    ids=["today", "day-90", "day-91", "past"],
)
def test_the_renewal_window_is_today_through_day_90(days: int, soon: bool) -> None:
    u = urgency([], [acct(1, renewal_date=TODAY + timedelta(days=days))], TODAY, CFG)
    assert u.renewal_soon is soon
    assert u.value == pytest.approx(0.4 if soon else 0.0)


def test_prospects_and_unknown_severities_add_no_urgency() -> None:
    p = AccountIn(id=1, name="P1", segment="enterprise", arr=0, is_prospect=True, pipeline_value=1,
                  renewal_date=TODAY + timedelta(days=5))  # fmt: skip
    u = urgency(["unknown", None], [p], TODAY, CFG)
    assert (u.value, u.max_severity, u.renewal_soon) == (0.0, None, False)


# --- strategic fit --------------------------------------------------------------------------------------


def test_strategic_fit_is_the_goal_weighted_rating_over_three() -> None:
    s = strategic_fit({"enterprise_readiness": 3, "retention": 1, "self_serve_growth": 0}, CFG)
    # 0.40 x 3/3 + 0.35 x 1/3 + 0.25 x 0/3 = 0.516667
    assert s.value == pytest.approx(0.516667, abs=1e-6)
    assert [(g.goal, g.rating, round(g.contribution, 6)) for g in s.goals] == [
        ("enterprise_readiness", 3, 0.4),
        ("retention", 1, 0.116667),
        ("self_serve_growth", 0, 0.0),
    ]


def test_unrated_or_partly_rated_needs_have_no_strategic_value() -> None:
    assert strategic_fit(None, CFG).value is None
    partial = strategic_fit({"enterprise_readiness": 3}, CFG)  # a goal added after the rating
    assert partial.value is None
    assert strategic_fit({"enterprise_readiness": 0, "retention": 0, "self_serve_growth": 0,
                          "a_goal_since_removed": 3}, CFG).value == 0.0  # fmt: skip


# --- priority, quadrant, owner, ranking -----------------------------------------------------------------


def test_priority_is_0_to_100_with_points_per_component() -> None:
    p = priority(0.619086, 0.516667, 1.0, CFG)
    # 100 x (0.4 x 0.619086 + 0.4 x 0.516667 + 0.2 x 1.0) = 65.4301
    assert p.value == pytest.approx(65.4301, abs=1e-3)
    assert p.contributions == pytest.approx(
        {"demand": 24.7634, "strategic": 20.6667, "urgency": 20.0}, abs=1e-3
    )
    assert p.rated is True
    assert priority(0, 0, 0, CFG).value == 0.0
    assert priority(1, 1, 1, CFG).value == pytest.approx(100.0)


def test_an_unrated_need_renormalises_the_other_weights() -> None:
    p = priority(0.619086, None, 1.0, CFG)  # 100 x (0.4 x 0.619086 + 0.2 x 1.0) / 0.6 = 74.6057
    assert p.value == pytest.approx(74.6057, abs=1e-3)
    assert p.weights == pytest.approx({"demand": 2 / 3, "urgency": 1 / 3})
    assert p.rated is False and "strategic" not in p.contributions


@pytest.mark.parametrize(
    ("d", "s", "expected"),
    [
        (0.6, 0.5, "clear_win"),  # both cut-offs are inclusive
        (0.2, 0.9, "strategic_bet"),
        (0.9, 0.1, "popular_off_strategy"),
        (0.59, 0.49, "park"),
        (0.0, 0.0, "park"),  # no supporters, no fit
        (0.9, None, None),  # not rated: no quadrant
    ],
)
def test_quadrant_separates_popular_from_strategic(d: float, s: float | None, expected: str | None) -> None:
    assert quadrant(d, s, CFG) == expected


def test_routing_goes_to_the_owning_pm_by_product_area() -> None:
    cfg = replace(CFG, owners={"security_admin": "platform", "sharing": "reporting"}, default_owner="triage")
    assert owner_for("security_admin", cfg) == "platform"
    assert owner_for("sharing", cfg) == "reporting"
    assert owner_for("other", cfg) == "triage"
    assert owner_for(None, cfg) == "triage"


def test_ties_break_on_more_accounts_then_the_older_need() -> None:
    rows = [(50.0, 2, 7), (50.0, 3, 9), (50.0, 3, 4), (70.0, 1, 8)]  # (priority, accounts, need id)
    assert [r[2] for r in sorted(rows, key=lambda r: rank_key(*r))] == [8, 4, 9, 7]


@pytest.mark.parametrize(
    ("now", "last", "due"),
    [
        (1, None, True),  # never rated: rate it
        (2, 1, False),
        (3, 2, True),  # crossed 3
        (3, 3, False),
        (12, 2, True),  # crossed 3 and 10 at once: one rating
        (11, 10, False),
        (2, 5, False),  # support went down: no re-rating
        (10, 9, True),  # crossed 10
    ],
)
def test_strategic_fit_is_due_at_creation_and_when_accounts_cross_3_and_10(
    now: int, last: int | None, due: bool
) -> None:
    assert fit_due(now, last, CFG) is due


# --- the whole breakdown, and config driving the ranking ------------------------------------------------


def test_breakdown_puts_every_component_together() -> None:
    accounts = [
        acct(1, renewal_date=TODAY + timedelta(days=30)),
        prospect(2, 200_000),
        acct(3, "mid_market", 60_000),
    ]
    b = breakdown(
        accounts=accounts,
        severities=["blocker", "important"],
        ratings={"enterprise_readiness": 3, "retention": 1, "self_serve_growth": 0},
        product_area="security_admin",
        today=TODAY,
        cfg=replace(CFG, owners={"security_admin": "platform"}),
    )
    assert b.priority.value == pytest.approx(65.4301, abs=1e-3)
    assert (b.quadrant, b.owner) == ("clear_win", "platform")
    assert (b.demand.accounts, b.urgency.renewal_soon) == (3, True)
    assert b.strategic.value == pytest.approx(0.516667)


def test_changing_weights_in_config_changes_the_ranking() -> None:
    popular = dict(accounts=[acct(i, arr=400_000) for i in range(5)], severities=["important"],
                   ratings={"enterprise_readiness": 0, "retention": 1, "self_serve_growth": 0})  # fmt: skip
    strategic = dict(accounts=[acct(9, "smb", 20_000)], severities=["nice_to_have"],
                     ratings={"enterprise_readiness": 3, "retention": 1, "self_serve_growth": 0})  # fmt: skip
    common = dict(product_area=None, today=TODAY)

    def order(cfg: PrioritiesConfig) -> list[str]:
        scores = {name: breakdown(**kw, **common, cfg=cfg).priority.value  # type: ignore[arg-type]
                  for name, kw in (("popular", popular), ("strategic", strategic))}  # fmt: skip
        return sorted(scores, key=lambda n: -scores[n])

    assert order(CFG) == ["popular", "strategic"]
    assert order(replace(CFG, w_demand=0.2, w_strategic=0.7, w_urgency=0.1)) == ["strategic", "popular"]


# --- config ---------------------------------------------------------------------------------------------


def test_the_shipped_config_loads_with_three_goals_and_weights_that_sum_to_one() -> None:
    cfg = load_priorities(CONFIG)
    assert [(g.key, g.weight) for g in cfg.goals] == [
        ("enterprise_readiness", 0.40),
        ("retention", 0.35),
        ("self_serve_growth", 0.25),
    ]
    assert all(g.description for g in cfg.goals)
    assert (cfg.w_demand, cfg.w_strategic, cfg.w_urgency) == (0.4, 0.4, 0.2)
    assert set(cfg.segment_weights) == {"enterprise", "mid_market", "smb"}
    assert cfg.rerate_at_accounts == (3, 10)


@pytest.mark.parametrize("broken", ["goals", "weights"])
def test_config_whose_weights_do_not_sum_to_one_is_refused(tmp_path: Path, broken: str) -> None:
    text = CONFIG.read_text(encoding="utf-8")
    text = (
        text.replace("weight: 0.25", "weight: 0.30")
        if broken == "goals"
        else text.replace("urgency: 0.20", "urgency: 0.30")
    )
    bad = tmp_path / "priorities.yaml"
    bad.write_text(text, encoding="utf-8")
    with pytest.raises(ValueError, match="sum to 1"):
        load_priorities(bad)


def test_an_unknown_segment_gets_the_lowest_weight_and_is_flagged() -> None:
    d = demand([acct(1, "galactic", 100_000)], CFG)
    assert d.revenue == pytest.approx(80_000)  # smb's 0.8, never more than a known segment
    assert d.gaps == ("A1: unknown segment 'galactic'",)


@pytest.mark.parametrize(
    ("old", "new", "message"),
    [
        (
            "  demand: 0.40\n  strategic: 0.40\n  urgency: 0.20\n",
            "  demand: 0.00\n  strategic: 1.00\n  urgency: 0.00\n",
            "demand and urgency",
        ),
        ("  demand: 0.40\n  strategic: 0.40\n", "  demand: -0.10\n  strategic: 0.90\n", "negative"),
        ("  renewal_weight: 0.4\n", "  renewal_weight: 0.5\n", "sum to 1"),
        ("  model: fast\n", "  model: opus\n", "fast or smart"),
    ],
    ids=["unrated-divides-by-zero", "negative-weight", "urgency-weights", "unknown-model-alias"],
)
def test_config_that_would_break_scoring_is_refused(tmp_path: Path, old: str, new: str, message: str) -> None:
    text = CONFIG.read_text(encoding="utf-8")
    assert old in text
    bad = tmp_path / "priorities.yaml"
    bad.write_text(text.replace(old, new, 1), encoding="utf-8")
    with pytest.raises(ValueError, match=message):
        load_priorities(bad)
