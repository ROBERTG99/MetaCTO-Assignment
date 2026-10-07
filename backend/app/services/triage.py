"""The PM inbox (spec F5): suggestions, claim disputes, the audit sample and failures; accept, reject, undo.

Nothing is deleted: every decision changes a state and, when a link changes, appends LinkEvents that say
who did it (the PM names themselves until there is auth, spec A3). Decisions are compare-and-set, so a
double click applies once and the second gets 409.
"""

from typing import Any

from sqlalchemy import update
from sqlmodel import Session, col, func, select

from app.ai.index import request_text
from app.ai.pipeline import Deps, live_need, new_need_for
from app.errors import AppError, not_found
from app.models import (
    AISuggestion,
    LinkAction,
    LinkActor,
    LinkEvent,
    Need,
    NeedStatus,
    Request,
    RequestStatus,
    SuggestionKind,
    SuggestionState,
    Support,
    SupportLinkStatus,
    utcnow,
)
from app.scoring import refresh_need


def _kind(s: AISuggestion) -> str | None:
    if s.state == SuggestionState.proposed and s.support_id is not None:
        return "claim"
    if (
        s.state == SuggestionState.proposed
        and s.kind == SuggestionKind.duplicate
        and s.request_id is not None
    ):
        return "suggestion"
    if (
        s.state == SuggestionState.applied
        and s.audit_sample
        and s.audit_verdict is None
        and s.request_id is not None
    ):
        return "audit"
    return None


def _need(n: Need | None) -> dict[str, Any] | None:
    if n is None:
        return None
    return {
        "id": n.id,
        "title": n.title,
        "problem": n.problem,
        "persona": n.persona,
        "product_area": n.product_area,
    }


def list_triage(session: Session) -> dict[str, Any]:
    items = []
    for s in session.exec(
        select(AISuggestion).order_by(col(AISuggestion.created_at), col(AISuggestion.id))
    ).all():
        kind = _kind(s)
        if kind is None:
            continue
        item: dict[str, Any] = {
            "id": s.id,
            "kind": kind,
            "routing_score": s.routing_score,
            "label": s.label,
            "model_confidence": s.model_confidence,
            "rationale": s.rationale,
            "quotes": s.quotes,
            "created_at": s.created_at,
            "need": None,
            "alternative_need": None,
            "request": None,
            "support": None,
        }
        if s.request_id is not None:
            item["need"] = _need(session.get(Need, s.need_id) if s.need_id else None)
            r = session.get(Request, s.request_id)
            if r is not None:
                item["request"] = {"id": r.id, "title": r.title, "description": r.description,
                                   "need_statement": r.need_statement, "persona": r.persona}  # fmt: skip
        if s.support_id is not None:
            sup = session.get(Support, s.support_id)
            if sup is not None:
                # accept confirms the claimed need; the model's alternative (if any) is shown separately
                item["need"] = _need(session.get(Need, sup.need_id))
                if s.need_id != sup.need_id:
                    item["alternative_need"] = _need(session.get(Need, s.need_id) if s.need_id else None)
                item["support"] = {"id": sup.id, "why_it_matters": sup.why_it_matters, "severity": sup.severity,
                                   "claimed_need": _need(session.get(Need, sup.need_id)), "reason": sup.review_reason}  # fmt: skip
        items.append(item)
    failed = session.exec(
        select(Request).where(Request.status == RequestStatus.needs_review).order_by(col(Request.id))
    ).all()
    return {
        "items": items,
        "needs_review": [
            {"id": r.id, "title": r.title, "reason": r.needs_review_reason, "attempts": r.attempts}
            for r in failed
        ],
    }


def _get(session: Session, suggestion_id: int) -> tuple[AISuggestion, str]:
    s = session.get(AISuggestion, suggestion_id)
    if s is None:
        raise not_found("Suggestion", suggestion_id)
    kind = _kind(s)
    if kind is None:
        raise AppError(409, "not_pending", f"Suggestion {s.id} is not waiting for a decision")
    return s, kind


def _decide_once(session: Session, s: AISuggestion, kind: str, by: str, state: SuggestionState | None,
                 verdict: str | None = None) -> None:  # fmt: skip
    """Compare-and-set in the same transaction: only one of two concurrent decisions gets through."""
    stmt = update(AISuggestion).where(col(AISuggestion.id) == s.id)
    if kind == "audit":
        stmt = stmt.where(col(AISuggestion.audit_verdict).is_(None))
    else:
        stmt = stmt.where(col(AISuggestion.state) == SuggestionState.proposed)
    values: dict[str, Any] = {"decided_by": by, "decided_at": utcnow()}
    if state is not None:
        values["state"] = state
    if verdict is not None:
        values["audit_verdict"] = verdict
    if session.exec(stmt.values(**values)).rowcount != 1:
        session.rollback()
        raise AppError(409, "not_pending", f"Suggestion {s.id} was decided by someone else")
    session.refresh(s)


def accept(session: Session, suggestion_id: int, by: str, deps: Deps) -> dict[str, Any]:
    s, kind = _get(session, suggestion_id)
    moved: Request | None = None
    if kind == "audit":
        _decide_once(session, s, kind, by, None, verdict="correct")
    elif kind == "claim":
        sup = session.get(Support, s.support_id)
        assert sup is not None
        if live_need(session, sup.need_id) != sup.need_id:
            raise AppError(409, "need_gone", f"Need {sup.need_id} was merged; reject the claim instead")
        _decide_once(session, s, kind, by, SuggestionState.accepted)
        sup.link_status, sup.updated_at = SupportLinkStatus.confirmed, utcnow()
        session.add(sup)
        refresh_need(session, sup.need_id, deps.priorities)
    else:
        r = session.get(Request, s.request_id)
        target = live_need(session, s.need_id)  # follow a merge that happened after the suggestion
        if r is None or target is None:
            raise AppError(409, "need_gone", f"Need {s.need_id} no longer exists")
        _decide_once(session, s, kind, by, SuggestionState.accepted)
        r.need_id = target
        session.add(LinkEvent(action=LinkAction.link, actor=LinkActor.pm, actor_id=by, need_id=target,
                              request_id=r.id, suggestion_id=s.id, routing_score=s.routing_score))  # fmt: skip
        for other in session.exec(
            select(AISuggestion).where(
                AISuggestion.request_id == r.id,
                AISuggestion.state == SuggestionState.proposed,
                AISuggestion.id != s.id,
                AISuggestion.kind == SuggestionKind.duplicate,
            )
        ).all():
            other.state, other.decided_by, other.decided_at = SuggestionState.rejected, by, utcnow()
            session.add(other)
        session.add(r)
        session.flush()
        refresh_need(session, target, deps.priorities)
        moved = r
    session.commit()
    if moved is not None and moved.id is not None and moved.need_id is not None:
        deps.search.move_request(moved.id, moved.need_id, request_text(moved))
    return {"id": s.id, "kind": kind, "state": s.state, "audit_verdict": s.audit_verdict, "need_id": None}


def _own_need(session: Session, r: Request, by: str, reason: str, deps: Deps) -> Need:
    """Move a request to a need of its own: an unlink and a link, both by the PM. Returns the new need."""
    old_id = r.need_id
    need = new_need_for(session, r, "pm")
    assert need.id is not None
    if old_id is not None:
        session.add(LinkEvent(action=LinkAction.unlink, actor=LinkActor.pm, actor_id=by, need_id=old_id,
                              request_id=r.id, reason=reason))  # fmt: skip
    session.add(LinkEvent(action=LinkAction.link, actor=LinkActor.pm, actor_id=by, need_id=need.id,
                          request_id=r.id, reason=reason))  # fmt: skip
    r.need_id = need.id
    session.add(r)
    session.flush()
    if old_id is not None:
        old = session.get(Need, old_id)
        members = session.exec(
            select(func.count()).select_from(Request).where(Request.need_id == old_id)
        ).one()
        supporters = session.exec(
            select(func.count())
            .select_from(Support)
            .where(Support.need_id == old_id, Support.link_status != SupportLinkStatus.rejected)
        ).one()
        if (
            old is not None
            and old.created_by == "ai"
            and old.status == NeedStatus.open
            and not members
            and not supporters
        ):
            old.status, old.merged_into_id = NeedStatus.merged, need.id  # emptied: never offered again
            session.add(old)
        refresh_need(session, old_id, deps.priorities)
    refresh_need(session, need.id, deps.priorities)
    return need


def reject(session: Session, suggestion_id: int, by: str, deps: Deps) -> dict[str, Any]:
    s, kind = _get(session, suggestion_id)
    need: Need | None = None
    r: Request | None = None
    if kind == "audit":
        r = session.get(Request, s.request_id)
        assert r is not None
        _decide_once(session, s, kind, by, SuggestionState.undone, verdict="false_merge")
        if r.need_id is not None and r.need_id == s.need_id:  # still where the auto-link put it
            need = _own_need(session, r, by, "audit: false_merge", deps)
    elif kind == "claim":
        sup = session.get(Support, s.support_id)
        assert sup is not None
        _decide_once(session, s, kind, by, SuggestionState.rejected)
        sup.link_status, sup.updated_at = SupportLinkStatus.rejected, utcnow()
        session.add(sup)
        session.add(LinkEvent(action=LinkAction.unlink, actor=LinkActor.pm, actor_id=by, need_id=sup.need_id,
                              support_id=sup.id, reason="claim rejected"))  # fmt: skip
    else:
        r = session.get(Request, s.request_id)
        assert r is not None
        _decide_once(session, s, kind, by, SuggestionState.rejected)
        open_other = session.exec(
            select(AISuggestion).where(
                AISuggestion.request_id == r.id,
                AISuggestion.state == SuggestionState.proposed,
                AISuggestion.kind == SuggestionKind.duplicate,
                AISuggestion.id != s.id,
            )
        ).first()
        if open_other is None and r.need_id is None:
            need = _own_need(session, r, by, "suggestion rejected", deps)
    session.commit()
    if need is not None and r is not None and r.id is not None and need.id is not None:
        deps.search.add_need(need)
        deps.search.move_request(r.id, need.id, request_text(r))
    return {"id": s.id, "kind": kind, "state": s.state, "audit_verdict": s.audit_verdict,
            "need_id": need.id if need else None}  # fmt: skip


def unlink(session: Session, request_id: int, by: str, deps: Deps) -> dict[str, Any]:
    r = session.get(Request, request_id)
    if r is None:
        raise not_found("Request", request_id)
    if r.need_id is None:
        raise AppError(409, "not_linked", f"Request {request_id} is not linked to a need")
    others = session.exec(
        select(func.count()).select_from(Request).where(Request.need_id == r.need_id, Request.id != r.id)
    ).one()
    if not others:
        raise AppError(409, "already_alone", f"Request {request_id} is already the only request in its need")
    for s in session.exec(
        select(AISuggestion).where(
            AISuggestion.request_id == r.id,
            col(AISuggestion.state).in_([SuggestionState.applied, SuggestionState.accepted]),
            AISuggestion.kind == SuggestionKind.duplicate,
        )
    ).all():
        if s.audit_sample and s.audit_verdict is None:
            s.audit_verdict = "false_merge"  # the PM caught it: count it in M4, don't lose it from the sample
        s.state, s.decided_by, s.decided_at = SuggestionState.undone, by, utcnow()
        session.add(s)
    need = _own_need(session, r, by, "undo", deps)
    session.commit()
    assert r.id is not None and need.id is not None
    deps.search.add_need(need)
    deps.search.move_request(r.id, need.id, request_text(r))
    return {"request_id": r.id, "need_id": need.id, "title": need.title}


def similar(session: Session, q: str, deps: Deps, k: int = 5) -> list[dict[str, Any]]:
    """The door (spec F1): nearest needs by embedding only, no model call."""
    hits = deps.search.search(q, k=k * 3)
    needs = {n.id: n for n in session.exec(select(Need).where(col(Need.id).in_([i for i, _ in hits]))).all()}
    out = []
    for need_id, score in hits:
        n = needs.get(need_id)
        if n is None or n.status == NeedStatus.merged:
            continue
        out.append({"need_id": n.id, "title": n.title, "problem": n.problem, "persona": n.persona,
                    "product_area": n.product_area, "status": n.status, "score": round(score, 4)})  # fmt: skip
        if len(out) == k:
            break
    return out
