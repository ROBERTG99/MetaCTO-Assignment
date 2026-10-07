"""Deterministic priority math (spec §8). Weights in config/priorities.yaml."""

import math
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path

import yaml
from sqlmodel import Session, col, select

from app.models import Account, Need, Request, Requester, Support, SupportLinkStatus, utcnow


@dataclass(frozen=True)
class PrioritiesConfig:
    w_demand: float = 0.40
    w_urgency: float = 0.25
    w_strategic: float = 0.35
    p_win: float = 0.2
    r_cap: float = 5_000_000
    severity_weight: float = 0.6
    renewal_weight: float = 0.4
    renewal_days: int = 90
    severity: dict[str, float] = field(
        default_factory=lambda: {"blocker": 1.0, "important": 0.5, "nice_to_have": 0.2, "unknown": 0.0}
    )


def load_priorities(path: Path) -> PrioritiesConfig:
    d = yaml.safe_load(path.read_text(encoding="utf-8"))
    return PrioritiesConfig(
        w_demand=float(d["weights"]["demand"]),
        w_urgency=float(d["weights"]["urgency"]),
        w_strategic=float(d["weights"]["strategic"]),
        p_win=float(d["demand"]["p_win"]),
        r_cap=float(d["demand"]["r_cap"]),
        severity_weight=float(d["urgency"]["severity_weight"]),
        renewal_weight=float(d["urgency"]["renewal_weight"]),
        renewal_days=int(d["urgency"]["renewal_days"]),
        severity={k: float(v) for k, v in d["severity"].items()},
    )


def refresh_need(session: Session, need_id: int, cfg: PrioritiesConfig, today: date | None = None) -> Need:
    """Recompute demand, urgency and priority from member requests and confirmed supports (not claims)."""
    today = today or date.today()
    need = session.get(Need, need_id)
    if need is None:
        raise ValueError(f"need {need_id} not found")
    members = session.exec(select(Request).where(Request.need_id == need_id)).all()
    supports = session.exec(
        select(Support, Requester)
        .join(Requester, col(Requester.id) == Support.requester_id)
        .where(Support.need_id == need_id, Support.link_status == SupportLinkStatus.confirmed)
    ).all()
    account_ids = {r.account_id for r in members if r.account_id is not None}
    account_ids |= {p.account_id for _, p in supports if p.account_id is not None}
    accounts = (
        session.exec(select(Account).where(col(Account.id).in_(account_ids))).all() if account_ids else []
    )
    revenue = sum(cfg.p_win * (a.pipeline_value or 0) if a.is_prospect else a.arr for a in accounts)
    demand = (
        min(1.0, math.log10(1 + revenue / 1000) / math.log10(1 + cfg.r_cap / 1000)) if revenue > 0 else 0.0
    )
    severities = [cfg.severity.get(str(s.severity), 0.0) for s, _ in supports]
    severities += [cfg.severity.get(r.severity_signal or "unknown", 0.0) for r in members]
    customers = [a for a in accounts if not a.is_prospect and a.arr > 0]
    horizon = today + timedelta(days=cfg.renewal_days)
    renewing = sum(a.arr for a in customers if a.renewal_date and today <= a.renewal_date <= horizon)
    total_arr = sum(a.arr for a in customers)
    share = renewing / total_arr if total_arr else 0.0
    urgency = cfg.severity_weight * max(severities, default=0.0) + cfg.renewal_weight * share
    parts = [(cfg.w_demand, demand), (cfg.w_urgency, urgency)]
    if need.strategic_fit is not None:  # rated by the model (should); otherwise left out and renormalised
        parts.append((cfg.w_strategic, need.strategic_fit))
    weight = sum(w for w, _ in parts)
    need.demand, need.urgency = demand, urgency
    need.priority_score = 100 * sum(w * v for w, v in parts) / weight if weight else 0.0
    need.updated_at = utcnow()
    session.add(need)
    return need
