"""Finding needs, reading one need, and adding support (a requester claim).

Filters run in SQL. Counts, sorting and paging run in Python over the filtered set: the backlog is
small by design (spec A2, ADR 0005), and the same counts must agree between list and detail.
"""

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime

from sqlalchemy import exists, or_
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, col, select

from app.errors import AppError, not_found
from app.models import (
    Account,
    LinkAction,
    LinkActor,
    LinkEvent,
    Need,
    NeedStatus,
    Request,
    Requester,
    Segment,
    Support,
    SupportLinkStatus,
    utcnow,
)
from app.schemas import (
    AccountOut,
    NeedDetail,
    NeedPage,
    NeedRequestOut,
    NeedSort,
    NeedSummary,
    PriorityBreakdown,
    SupportCreate,
    SupportOut,
)
from app.scoring import PrioritiesConfig, rank_key
from app.services import need_detail as detail
from app.services import priority
from app.services.requests import get_requester


@dataclass
class _Stats:
    supporters: set[int] = field(default_factory=set)
    accounts: set[int] = field(default_factory=set)
    claimed: int = 0
    requests: int = 0
    last_request_at: datetime | None = None


def _stats(session: Session, need_ids: list[int]) -> dict[int, _Stats]:
    stats: dict[int, _Stats] = defaultdict(_Stats)
    if not need_ids:
        return stats
    rows = session.exec(
        select(Request.need_id, Request.requester_id, Request.account_id, Request.created_at).where(
            col(Request.need_id).in_(need_ids)
        )
    ).all()
    for need_id, requester_id, account_id, created_at in rows:
        s = stats[need_id]  # type: ignore[index]
        s.requests += 1
        s.supporters.add(requester_id)
        if account_id is not None:
            s.accounts.add(account_id)
        if s.last_request_at is None or created_at > s.last_request_at:
            s.last_request_at = created_at
    supports = session.exec(
        select(Support.need_id, Support.requester_id, Support.link_status, Requester.account_id)
        .join(Requester, col(Requester.id) == Support.requester_id)
        .where(col(Support.need_id).in_(need_ids))
    ).all()
    for need_id, requester_id, status, account_id in supports:
        s = stats[need_id]
        if status == SupportLinkStatus.confirmed:
            s.supporters.add(requester_id)
            if account_id is not None:
                s.accounts.add(account_id)
        elif status == SupportLinkStatus.claimed:
            s.claimed += 1
    return stats


def _summary(need: Need, s: _Stats, b: PriorityBreakdown) -> NeedSummary:
    assert need.id is not None
    return NeedSummary(
        id=need.id,
        title=need.title,
        problem=need.problem,
        persona=need.persona,
        product_area=need.product_area,
        status=need.status,
        priority_score=b.priority,
        breakdown=b,
        support_count=len(s.supporters),
        claimed_support_count=s.claimed,
        request_count=s.requests,
        account_count=len(s.accounts),
        last_request_at=s.last_request_at,
        created_at=need.created_at,
    )


def list_needs(
    session: Session,
    *,
    q: str | None,
    status: NeedStatus | None,
    product_area: str | None,
    segment: Segment | None,
    sort: NeedSort,
    page: int,
    page_size: int,
    cfg: PrioritiesConfig,
) -> NeedPage:
    query = select(Need)
    query = query.where(Need.status == status) if status else query.where(Need.status != NeedStatus.merged)
    if product_area:
        query = query.where(Need.product_area == product_area)
    if q and q.strip():
        term = q.strip()
        member_match = exists().where(
            col(Request.need_id) == col(Need.id),
            or_(
                col(Request.title).icontains(term, autoescape=True),
                col(Request.description).icontains(term, autoescape=True),
            ),
        )
        query = query.where(
            or_(
                col(Need.title).icontains(term, autoescape=True),
                col(Need.problem).icontains(term, autoescape=True),
                member_match,
            )
        )
    if segment:
        via_request = exists().where(
            col(Request.need_id) == col(Need.id),
            col(Request.account_id) == col(Account.id),
            col(Account.segment) == segment,
        )
        via_support = exists().where(
            col(Support.need_id) == col(Need.id),
            col(Support.link_status) == SupportLinkStatus.confirmed,
            col(Support.requester_id) == col(Requester.id),
            col(Requester.account_id) == col(Account.id),
            col(Account.segment) == segment,
        )
        query = query.where(or_(via_request, via_support))
    needs = list(session.exec(query).all())
    stats = _stats(session, [n.id for n in needs if n.id is not None])
    bds = priority.breakdowns(session, needs, cfg)
    items = [_summary(n, stats[n.id], bds[n.id]) for n in needs if n.id is not None]
    if sort == "priority":
        items.sort(key=lambda n: rank_key(n.priority_score, n.breakdown.demand.accounts, n.id))
    elif sort == "support":
        items.sort(key=lambda n: (-n.support_count, n.id))
    else:  # recent: newest member request first; needs without requests use their creation time
        items.sort(key=lambda n: ((n.last_request_at or n.created_at).timestamp(), n.id), reverse=True)
    start = (page - 1) * page_size
    return NeedPage(items=items[start : start + page_size], total=len(items), page=page, page_size=page_size)


def get_need(session: Session, need_id: int, cfg: PrioritiesConfig) -> NeedDetail:
    need = session.get(Need, need_id)
    if need is None:
        raise not_found("Need", need_id)
    stats = _stats(session, [need_id])[need_id]
    b = priority.breakdowns(session, [need], cfg)[need_id]
    accounts = {a.id: a for a in session.exec(select(Account)).all()}
    people = {r.id: r for r in session.exec(select(Requester)).all()}

    def account_name(account_id: int | None) -> str | None:
        return accounts[account_id].name if account_id in accounts else None

    requests = session.exec(
        select(Request).where(Request.need_id == need_id).order_by(col(Request.created_at))
    ).all()
    supports = session.exec(
        select(Support).where(Support.need_id == need_id).order_by(col(Support.created_at))
    ).all()
    member_ids = [r.id for r in requests if r.id is not None]
    return NeedDetail(
        **_summary(need, stats, b).model_dump(),
        origin=detail.origin(session, need),
        evidence=detail.evidence(session, need, member_ids),
        updates=detail.updates(session, need_id),
        audit_trail=detail.audit_trail(session, need, member_ids),
        job_to_be_done=need.job_to_be_done,
        merged_into_id=need.merged_into_id,
        requests=[
            NeedRequestOut(
                id=r.id,
                title=r.title,
                description=r.description,
                source=r.source,
                status=r.status,
                requester_name=people[r.requester_id].name,
                account_name=account_name(r.account_id),
                created_at=r.created_at,
                analysis=detail.analysis(session, r),
                link=detail.link(session, r, need_id),
            )
            for r in requests
            if r.id is not None
        ],
        supports=[
            _support_out(s, people[s.requester_id], account_name(people[s.requester_id].account_id))
            for s in supports
        ],
        accounts=[AccountOut.model_validate(accounts[a]) for a in sorted(stats.accounts)],
    )


def _support_out(s: Support, requester: Requester, account: str | None) -> SupportOut:
    assert s.id is not None
    return SupportOut(
        id=s.id,
        need_id=s.need_id,
        requester_id=s.requester_id,
        requester_name=requester.name,
        account_name=account,
        why_it_matters=s.why_it_matters,
        severity=s.severity,
        link_status=s.link_status,
        created_at=s.created_at,
    )


def _find_support(session: Session, need_id: int, requester_id: int) -> Support | None:
    return session.exec(
        select(Support).where(Support.need_id == need_id, Support.requester_id == requester_id)
    ).first()


def _update_support(support: Support, body: SupportCreate) -> None:
    support.severity, support.updated_at = body.severity, utcnow()
    if body.why_it_matters is not None:  # omitted on a repeat: keep the stored reason
        support.why_it_matters = body.why_it_matters


def add_support(session: Session, need_id: int, body: SupportCreate) -> tuple[SupportOut, bool]:
    """Idempotent per (need, requester). Returns the support and whether it was created.

    A new support is a requester claim: stored as `claimed` with a LinkEvent, and only counted once
    the intake workflow confirms it. A repeat updates severity (and why, if sent) and adds no event.
    Two first supports racing each other (a double click) end in the same row: the loser of the
    unique constraint rolls back and updates the winner's row.
    """
    need = session.get(Need, need_id)
    if need is None:
        raise not_found("Need", need_id)
    if need.status == NeedStatus.merged:
        raise AppError(
            409,
            "need_merged",
            f"Need {need_id} was merged into need {need.merged_into_id}"
            if need.merged_into_id
            else f"Need {need_id} was emptied and closed",
        )
    requester = get_requester(session, body.requester_id)
    support = _find_support(session, need_id, body.requester_id)
    created = support is None
    if support is None:
        support = Support(
            need_id=need_id,
            requester_id=body.requester_id,
            why_it_matters=body.why_it_matters or "",
            severity=body.severity,
            link_status=SupportLinkStatus.claimed,
        )
        session.add(support)
        try:
            session.flush()
        except IntegrityError:
            session.rollback()
            support = session.exec(
                select(Support).where(Support.need_id == need_id, Support.requester_id == body.requester_id)
            ).one()
            created = False
    if created:
        session.add(
            LinkEvent(
                action=LinkAction.link,
                actor=LinkActor.requester_claim,
                actor_id=str(body.requester_id),
                need_id=need_id,
                support_id=support.id,
            )
        )
    else:
        _update_support(support, body)
        session.add(support)
    session.commit()
    session.refresh(support)
    account = session.get(Account, requester.account_id) if requester.account_id else None
    return _support_out(support, requester, account.name if account else None), created
