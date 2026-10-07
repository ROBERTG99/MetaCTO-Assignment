"""The requester portal's reads (/portal): what any requester may see. PM-only data (revenue, accounts and
ARR, priority breakdowns, request descriptions, other supporters' reasons, internal notes, the audit trail)
stays on the PM routes, so a future auth layer can guard everything outside /portal by prefix."""

from typing import Any

from sqlmodel import Session, col, select

from app.errors import not_found
from app.models import Account, Need, Request, Requester, Segment, StakeholderUpdate, Support
from app.schemas import NeedSort
from app.scoring import PrioritiesConfig
from app.services import need_detail, needs


def list_needs(session: Session, *, q: str | None, status: Any, product_area: str | None, segment: Segment | None,
               sort: NeedSort, page: int, page_size: int, cfg: PrioritiesConfig) -> dict[str, Any]:  # fmt: skip
    full = needs.list_needs(session, q=q, status=status, product_area=product_area, segment=segment, sort=sort,
                            page=page, page_size=page_size, cfg=cfg)  # fmt: skip
    keep = ("id", "title", "problem", "persona", "product_area", "status", "support_count", "account_count",
            "request_count", "last_request_at")  # fmt: skip
    return {"items": [{k: getattr(n, k) for k in keep} for n in full.items], "total": full.total,
            "page": full.page, "page_size": full.page_size}  # fmt: skip


def need(session: Session, need_id: int, requester_id: int | None) -> dict[str, Any]:
    n = session.get(Need, need_id)
    if n is None:
        raise not_found("Need", need_id)
    summary = next(
        (x for x in needs.list_needs(session, q=None, status=n.status, product_area=None, segment=None,
                                     sort="recent", page=1, page_size=10_000, cfg=PrioritiesConfig()).items
         if x.id == need_id),
        None,
    )  # fmt: skip
    people = {p.id: p for p in session.exec(select(Requester)).all()}
    accounts = {a.id: a.name for a in session.exec(select(Account)).all()}
    requests = session.exec(
        select(Request).where(Request.need_id == need_id).order_by(col(Request.created_at))
    ).all()
    supports = session.exec(
        select(Support).where(Support.need_id == need_id).order_by(col(Support.created_at))
    ).all()
    mine = session.exec(
        select(StakeholderUpdate)
        .where(StakeholderUpdate.need_id == need_id, StakeholderUpdate.status == "approved",
               StakeholderUpdate.kind == "requester_update", StakeholderUpdate.requester_id == requester_id)
        .order_by(col(StakeholderUpdate.approved_at).desc())
    ).all() if requester_id is not None else []  # fmt: skip
    return {
        "id": n.id, "title": n.title, "problem": n.problem, "persona": n.persona, "product_area": n.product_area,
        "status": n.status, "job_to_be_done": n.job_to_be_done, "origin": need_detail.origin(session, n),
        "support_count": summary.support_count if summary else 0,
        "account_count": summary.account_count if summary else 0,
        "request_count": summary.request_count if summary else len(requests),
        "last_request_at": summary.last_request_at if summary else None,
        "requests": [{"id": r.id, "title": r.title, "requester_name": people[r.requester_id].name,
                      "account_name": accounts.get(r.account_id) if r.account_id else None,
                      "created_at": r.created_at} for r in requests],
        "supporters": [{"id": s.id, "requester_name": people[s.requester_id].name,
                        "account_name": accounts.get(people[s.requester_id].account_id or -1),
                        "severity": s.severity, "link_status": s.link_status} for s in supports],
        "updates": [{"id": u.id, "body": u.approved_body or u.body, "approved_at": u.approved_at} for u in mine],
    }  # fmt: skip
