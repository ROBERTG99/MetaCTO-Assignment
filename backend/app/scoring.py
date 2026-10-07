"""Deterministic priority math (spec §8, ADR 0009). Pure functions; weights in config/priorities.yaml.

Every function returns its components, so the UI can show how a score was reached. Nothing here touches the
database: app/services/priority.py gathers the inputs and calls breakdown() when a need is read.
"""

import hashlib
import json
import math
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path
from typing import Literal

import yaml

Quadrant = Literal["clear_win", "strategic_bet", "popular_off_strategy", "park"]


@dataclass(frozen=True)
class Goal:
    key: str
    title: str
    description: str
    weight: float


DEFAULT_GOALS = (
    Goal("enterprise_readiness", "Enterprise readiness", "Enterprise rollout and security review", 0.40),
    Goal("retention", "Retention", "Existing customers renew and expand", 0.35),
    Goal("self_serve_growth", "Self-serve growth", "New teams succeed without a sales touch", 0.25),
)


@dataclass(frozen=True)
class PrioritiesConfig:
    w_demand: float = 0.40
    w_strategic: float = 0.40
    w_urgency: float = 0.20
    goals: tuple[Goal, ...] = DEFAULT_GOALS
    p_win: float = 0.2
    r_cap: float = 5_000_000
    segment_weights: Mapping[str, float] = field(
        default_factory=lambda: {"enterprise": 1.0, "mid_market": 0.9, "smb": 0.8}
    )
    severity_weight: float = 0.6
    renewal_weight: float = 0.4
    renewal_days: int = 90
    severity: Mapping[str, float] = field(
        default_factory=lambda: {"blocker": 1.0, "important": 0.5, "nice_to_have": 0.2, "unknown": 0.0}
    )
    popular_cut: float = 0.60
    strategic_cut: float = 0.50
    owners: Mapping[str, str] = field(
        default_factory=lambda: {
            "security_admin": "platform",
            "performance": "platform",
            "embedded": "platform",
            "data_sources": "data",
            "export": "data",
            "sharing": "reporting",
            "alerts": "reporting",
            "collaboration": "reporting",
            "ui": "reporting",
            "mobile": "reporting",
            "onboarding": "growth",
            "localization": "growth",
        }
    )
    default_owner: str = "product-triage"
    fit_model: str = "fast"
    rerate_at_accounts: tuple[int, ...] = (3, 10)


@dataclass(frozen=True)
class AccountIn:
    id: int
    name: str
    segment: str
    arr: int | None
    is_prospect: bool = False
    pipeline_value: int | None = None
    renewal_date: date | None = None


@dataclass(frozen=True)
class Demand:
    value: float
    revenue: float
    customer_revenue: float
    prospect_revenue: float
    accounts: int
    customers: int
    prospects: int
    gaps: tuple[str, ...]


@dataclass(frozen=True)
class Urgency:
    value: float
    max_severity: str | None
    severity_score: float
    renewal_soon: bool
    renewing_accounts: tuple[str, ...]


@dataclass(frozen=True)
class GoalScore:
    goal: str
    weight: float
    rating: int | None
    contribution: float


@dataclass(frozen=True)
class Strategic:
    value: float | None
    goals: tuple[GoalScore, ...]


@dataclass(frozen=True)
class Priority:
    value: float
    contributions: Mapping[str, float]
    weights: Mapping[str, float]
    rated: bool


@dataclass(frozen=True)
class Breakdown:
    demand: Demand
    urgency: Urgency
    strategic: Strategic
    priority: Priority
    quadrant: Quadrant | None
    owner: str


def goals_digest(goals: tuple[Goal, ...]) -> str:
    """What the strategic-fit model is shown about the goals. Weights are left out: they don't change a rating,
    so recorded ratings stay valid when only weights change."""
    return hashlib.sha256(json.dumps([[g.key, g.title, g.description] for g in goals]).encode()).hexdigest()


def _sums_to_one(name: str, values: Iterable[float]) -> None:
    total = sum(values)
    if abs(total - 1.0) > 1e-9:
        raise ValueError(f"config/priorities.yaml: {name} must sum to 1 (they sum to {total:g})")


def load_priorities(path: Path) -> PrioritiesConfig:
    d = yaml.safe_load(path.read_text(encoding="utf-8"))
    goals = tuple(
        Goal(str(g["key"]), str(g["title"]), " ".join(str(g["description"]).split()), float(g["weight"]))
        for g in d["goals"]
    )
    w = d["weights"]
    weights = [float(w["demand"]), float(w["strategic"]), float(w["urgency"])]
    u = d["urgency"]
    every = [*weights, *(g.weight for g in goals), float(u["severity_weight"]), float(u["renewal_weight"])]
    every += [float(v) for v in d["segment_weights"].values()]
    if any(x < 0 for x in every):
        raise ValueError("config/priorities.yaml: weights can't be negative")
    _sums_to_one("weights", weights)
    _sums_to_one("goal weights", [g.weight for g in goals])
    _sums_to_one("urgency weights", [float(u["severity_weight"]), float(u["renewal_weight"])])
    if weights[0] + weights[2] <= 0:
        raise ValueError(
            "config/priorities.yaml: demand and urgency can't both be 0 (unrated needs use only them)"
        )
    if d["strategic_fit"]["model"] not in ("fast", "smart"):
        raise ValueError("config/priorities.yaml: strategic_fit.model must be fast or smart")
    if len({g.key for g in goals}) != len(goals):
        raise ValueError("config/priorities.yaml: goal keys must be unique")
    return PrioritiesConfig(
        w_demand=float(w["demand"]),
        w_strategic=float(w["strategic"]),
        w_urgency=float(w["urgency"]),
        goals=goals,
        p_win=float(d["demand"]["p_win"]),
        r_cap=float(d["demand"]["r_cap"]),
        segment_weights={k: float(v) for k, v in d["segment_weights"].items()},
        severity_weight=float(d["urgency"]["severity_weight"]),
        renewal_weight=float(d["urgency"]["renewal_weight"]),
        renewal_days=int(d["urgency"]["renewal_days"]),
        severity={k: float(v) for k, v in d["severity"].items()},
        popular_cut=float(d["quadrant"]["popular"]),
        strategic_cut=float(d["quadrant"]["strategic"]),
        owners={k: str(v) for k, v in d["owners"]["areas"].items()},
        default_owner=str(d["owners"]["default"]),
        fit_model=str(d["strategic_fit"]["model"]),
        rerate_at_accounts=tuple(sorted(int(n) for n in d["strategic_fit"]["rerate_at_accounts"])),
    )


def _unique(accounts: Iterable[AccountIn]) -> list[AccountIn]:
    return list({a.id: a for a in accounts}.values())


def demand(accounts: Iterable[AccountIn], cfg: PrioritiesConfig) -> Demand:
    """D = min(1, log10(1 + R/1000) / log10(1 + R_cap/1000)); each account counted once."""
    unique = _unique(accounts)
    customer = prospect = 0.0
    gaps: list[str] = []
    lowest = min(cfg.segment_weights.values(), default=1.0)
    for a in unique:
        if a.segment not in cfg.segment_weights:
            gaps.append(f"{a.name}: unknown segment {a.segment!r}")
        w = cfg.segment_weights.get(a.segment, lowest)  # an unknown segment never outweighs a known one
        if a.is_prospect:
            if not a.pipeline_value:
                gaps.append(f"{a.name}: no pipeline value on record")
            prospect += cfg.p_win * (a.pipeline_value or 0) * w
        else:
            if not a.arr:
                gaps.append(f"{a.name}: no ARR on record")
            customer += (a.arr or 0) * w
    revenue = customer + prospect
    value = (
        min(1.0, math.log10(1 + revenue / 1000) / math.log10(1 + cfg.r_cap / 1000)) if revenue > 0 else 0.0
    )
    prospects = sum(a.is_prospect for a in unique)
    return Demand(
        value, revenue, customer, prospect, len(unique), len(unique) - prospects, prospects, tuple(gaps)
    )


def urgency(
    severities: Iterable[str | None], accounts: Iterable[AccountIn], today: date, cfg: PrioritiesConfig
) -> Urgency:
    """U = severity_weight x the highest severity + renewal_weight x (a supporting customer renews in the window)."""
    scored = [(cfg.severity.get(s, 0.0), s) for s in severities if s]
    top_score, top = max(scored, default=(0.0, None))
    horizon = today + timedelta(days=cfg.renewal_days)
    renewing = tuple(
        a.name
        for a in _unique(accounts)
        if not a.is_prospect and a.renewal_date is not None and today <= a.renewal_date <= horizon
    )
    value = cfg.severity_weight * top_score + cfg.renewal_weight * bool(renewing)
    return Urgency(value, top if top_score > 0 else None, top_score, bool(renewing), renewing)


def strategic_fit(ratings: Mapping[str, int] | None, cfg: PrioritiesConfig) -> Strategic:
    """S = sum over goals of weight x rating / 3. None until every configured goal has a rating."""
    ratings = ratings or {}
    goals = tuple(
        GoalScore(
            g.key, g.weight, ratings.get(g.key), g.weight * ratings[g.key] / 3 if g.key in ratings else 0.0
        )
        for g in cfg.goals
    )
    rated = bool(ratings) and all(g.rating is not None for g in goals)
    return Strategic(sum(g.contribution for g in goals) if rated else None, goals)


def priority(d: float, s: float | None, u: float, cfg: PrioritiesConfig) -> Priority:
    """0-100. An unrated need leaves strategic out and renormalises the other weights (spec §8)."""
    parts = {"demand": (cfg.w_demand, d), "urgency": (cfg.w_urgency, u)}
    if s is not None:
        parts["strategic"] = (cfg.w_strategic, s)
    total = sum(w for w, _ in parts.values())
    weights = {k: w / total for k, (w, _) in parts.items()}
    contributions = {k: 100 * weights[k] * v for k, (_, v) in parts.items()}
    return Priority(min(100.0, max(0.0, sum(contributions.values()))), contributions, weights, s is not None)


def quadrant(d: float, s: float | None, cfg: PrioritiesConfig) -> Quadrant | None:
    if s is None:
        return None
    popular, strategic = d >= cfg.popular_cut, s >= cfg.strategic_cut
    if popular and strategic:
        return "clear_win"
    if strategic:
        return "strategic_bet"
    return "popular_off_strategy" if popular else "park"


def owner_for(product_area: str | None, cfg: PrioritiesConfig) -> str:
    return cfg.owners.get(product_area or "", cfg.default_owner)


def fit_due(accounts_now: int, last: int | None, cfg: PrioritiesConfig) -> bool:
    """Due when never rated, or when supporting accounts crossed a re-rating count since the last one."""
    if last is None:
        return True
    return any(last < n <= accounts_now for n in cfg.rerate_at_accounts)


def rank_key(priority_value: float, accounts: int, need_id: int) -> tuple[float, int, int]:
    """Sort key: higher priority, then more accounts, then the older need (lower id)."""
    return (-priority_value, -accounts, need_id)


def breakdown(
    *,
    accounts: Iterable[AccountIn],
    severities: Iterable[str | None],
    ratings: Mapping[str, int] | None,
    product_area: str | None,
    today: date,
    cfg: PrioritiesConfig,
) -> Breakdown:
    accounts = list(accounts)
    d, u, s = demand(accounts, cfg), urgency(severities, accounts, today, cfg), strategic_fit(ratings, cfg)
    p = priority(d.value, s.value, u.value, cfg)
    return Breakdown(d, u, s, p, quadrant(d.value, s.value, cfg), owner_for(product_area, cfg))
