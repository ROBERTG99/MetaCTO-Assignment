"""Priority on read (ADR 0009): gather each need's inputs, run app/scoring.py, queue strategic-fit ratings.

Nothing computed here is stored. Renewal windows move with the date and weights change with config, so a
stored score would go stale; the backlog is small (spec A2), so computing per read is cheap.
Only member requests and confirmed supports count (a claim counts once confirmed or accepted by a PM).
"""

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date

from sqlmodel import Session, col, select

from app.models import (
    Account,
    AIRun,
    GoalRating,
    Need,
    NeedStatus,
    Request,
    Requester,
    Support,
    SupportLinkStatus,
)
from app.schemas import (
    DemandOut,
    GoalRatingOut,
    PriorityBreakdown,
    QuadrantNeed,
    QuadrantView,
    StrategicOut,
    UrgencyOut,
)
from app.scoring import AccountIn, Breakdown, PrioritiesConfig, breakdown, fit_due, goals_digest, rank_key

UNDECIDED = (NeedStatus.open, NeedStatus.planned, NeedStatus.in_progress)


@dataclass
class _Inputs:
    account_ids: set[int] = field(default_factory=set)
    severities: list[str | None] = field(default_factory=list)


def _inputs(session: Session, need_ids: list[int]) -> dict[int, _Inputs]:
    out: dict[int, _Inputs] = defaultdict(_Inputs)
    if not need_ids:
        return out
    members = select(Request.need_id, Request.account_id, Request.severity_signal).where(
        col(Request.need_id).in_(need_ids)
    )
    for need_id, account_id, severity in session.exec(members).all():
        i = out[need_id]  # type: ignore[index]
        if account_id is not None:
            i.account_ids.add(account_id)
        i.severities.append(severity)
    confirmed = (
        select(Support.need_id, Requester.account_id, Support.severity)
        .join(Requester, col(Requester.id) == Support.requester_id)
        .where(col(Support.need_id).in_(need_ids), Support.link_status == SupportLinkStatus.confirmed)
    )
    for need_id, account_id, severity in session.exec(confirmed).all():
        i = out[need_id]
        if account_id is not None:
            i.account_ids.add(account_id)
        i.severities.append(str(severity))
    return out


def _account(a: Account) -> AccountIn:
    assert a.id is not None
    return AccountIn(a.id, a.name, str(a.segment), a.arr, a.is_prospect, a.pipeline_value, a.renewal_date)


def account_count(session: Session, need_id: int) -> int:
    return len(_inputs(session, [need_id])[need_id].account_ids)


def account_ids(session: Session, need_id: int) -> set[int]:
    """The accounts behind a need, as priority counts them: member requests and confirmed supports."""
    return set(_inputs(session, [need_id])[need_id].account_ids)


def _strategic_out(
    need: Need, b: Breakdown, rows: list[GoalRating], run: AIRun | None, cfg: PrioritiesConfig
) -> StrategicOut:
    by_goal = {r.goal: r for r in rows}
    titles = {g.key: g.title for g in cfg.goals}
    # a queued re-rating keeps showing the ratings in use until it finishes
    queued_or_failed = need.fit_status if need.fit_status in ("pending", "failed") else "not_rated"
    if not rows:
        status = queued_or_failed
    elif b.strategic.value is None or need.fit_goals_digest != goals_digest(cfg.goals):
        status = "stale"
    else:
        status = "rated"
    return StrategicOut(
        value=b.strategic.value,
        status=status,
        model=run.model if run else None,
        prompt_version=run.prompt_version if run else None,
        ai_run_id=run.id if run else None,
        rated_at_accounts=need.fit_accounts if rows else None,
        rerating_queued=need.fit_status == "pending" and bool(rows),
        error=need.fit_error if need.fit_status == "failed" else None,
        goals=[
            GoalRatingOut(
                goal=g.goal,
                title=titles[g.goal],
                weight=g.weight,
                rating=g.rating,
                contribution=g.contribution,
                rationale=by_goal[g.goal].rationale if g.goal in by_goal else None,
                quote=by_goal[g.goal].quote if g.goal in by_goal else None,
                quote_dropped=by_goal[g.goal].quote_dropped if g.goal in by_goal else False,
            )
            for g in b.strategic.goals
        ],
    )


def breakdowns(
    session: Session, needs: list[Need], cfg: PrioritiesConfig, today: date | None = None
) -> dict[int, PriorityBreakdown]:
    today = today or date.today()
    ids = [n.id for n in needs if n.id is not None]
    inputs = _inputs(session, ids)
    wanted = {i for x in inputs.values() for i in x.account_ids}
    accounts = {
        a.id: _account(a) for a in session.exec(select(Account).where(col(Account.id).in_(wanted))).all()
    }
    run_ids = [n.fit_run_id for n in needs if n.fit_run_id is not None]
    ratings: dict[int, list[GoalRating]] = defaultdict(list)
    for r in session.exec(select(GoalRating).where(col(GoalRating.ai_run_id).in_(run_ids))).all():
        ratings[r.ai_run_id].append(r)
    runs = {r.id: r for r in session.exec(select(AIRun).where(col(AIRun.id).in_(run_ids))).all()}
    out: dict[int, PriorityBreakdown] = {}
    for n in needs:
        if n.id is None:
            continue
        i = inputs[n.id]
        rows = ratings.get(n.fit_run_id or -1, [])
        b = breakdown(
            accounts=[accounts[a] for a in sorted(i.account_ids) if a in accounts],
            severities=i.severities,
            ratings={r.goal: r.rating for r in rows} or None,
            product_area=n.product_area,
            today=today,
            cfg=cfg,
        )
        d, u = b.demand, b.urgency
        out[n.id] = PriorityBreakdown(
            priority=b.priority.value,
            contributions=dict(b.priority.contributions),
            weights=dict(b.priority.weights),
            demand=DemandOut(
                value=d.value,
                revenue=d.revenue,
                customer_revenue=d.customer_revenue,
                prospect_revenue=d.prospect_revenue,
                accounts=d.accounts,
                customers=d.customers,
                prospects=d.prospects,
                gaps=list(d.gaps),
            ),
            urgency=UrgencyOut(
                value=u.value,
                max_severity=u.max_severity,
                severity_score=u.severity_score,
                renewal_soon=u.renewal_soon,
                renewing_accounts=list(u.renewing_accounts),
            ),
            strategic=_strategic_out(n, b, rows, runs.get(n.fit_run_id or -1), cfg),
            quadrant=b.quadrant,
            owner=b.owner,
        )
    return out


def quadrant_view(session: Session, cfg: PrioritiesConfig, today: date | None = None) -> QuadrantView:
    """Undecided needs (open, planned, in progress) by quadrant, highest priority first in each."""
    needs = list(session.exec(select(Need).where(col(Need.status).in_(UNDECIDED))).all())
    bds = breakdowns(session, needs, cfg, today)
    rows = sorted(
        (
            QuadrantNeed(
                id=n.id,
                title=n.title,
                product_area=n.product_area,
                owner=bds[n.id].owner,
                priority=bds[n.id].priority,
                demand=bds[n.id].demand.value,
                strategic=bds[n.id].strategic.value,
                account_count=bds[n.id].demand.accounts,
                quadrant=bds[n.id].quadrant,
            )
            for n in needs
            if n.id is not None
        ),
        key=lambda q: rank_key(q.priority, q.account_count, q.id),
    )
    view = QuadrantView(
        cutoffs={"popular": cfg.popular_cut, "strategic": cfg.strategic_cut},
        quadrants={k: [] for k in ("clear_win", "strategic_bet", "popular_off_strategy", "park")},
        not_rated=[],
    )
    for q in rows:
        (view.quadrants[q.quadrant] if q.quadrant else view.not_rated).append(q)
    return view


def queue_fit_if_due(session: Session, need_id: int, cfg: PrioritiesConfig) -> bool:
    """Queue a strategic-fit rating when the need is new, its supporting accounts crossed a re-rating count,
    its last rating failed, or its ratings were made against goals that have changed since.

    Called wherever membership or confirmed support changes. A rating already queued is left alone.
    """
    need = session.get(Need, need_id)
    if need is None or need.status == NeedStatus.merged or need.fit_status == "pending":
        return False
    accounts = account_count(session, need_id)
    stale = need.fit_status == "rated" and need.fit_goals_digest != goals_digest(cfg.goals)
    if not (need.fit_status == "failed" or stale or fit_due(accounts, need.fit_accounts, cfg)):
        return False
    need.fit_status, need.fit_accounts, need.fit_attempts, need.fit_error = "pending", accounts, 0, None
    session.add(need)
    return True
