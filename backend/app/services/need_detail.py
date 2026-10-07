"""What the need page explains: where the need came from, the AI reading of each request and how it joined,
the verified evidence, the updates supporters received, and the audit trail (CLAUDE.md rule 6)."""

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import or_
from sqlmodel import Session, col, select

from app.models import (
    AIRun,
    AISuggestion,
    GoalRating,
    LinkAction,
    LinkEvent,
    Need,
    NeedStatusChange,
    Request,
    Requester,
    StakeholderUpdate,
    SuggestionKind,
    SuggestionState,
)


def _aware(t: datetime) -> datetime:
    return t if t.tzinfo else t.replace(tzinfo=UTC)


def _source(run: AIRun | None) -> dict[str, Any] | None:
    return {"model": run.model, "prompt_version": run.prompt_version, "ai_run_id": run.id} if run else None


def origin(session: Session, need: Need) -> dict[str, Any]:
    first = session.exec(
        select(AISuggestion)
        .where(AISuggestion.need_id == need.id, AISuggestion.kind == SuggestionKind.new_need)
        .order_by(col(AISuggestion.created_at), col(AISuggestion.id))
    ).first()
    run = session.get(AIRun, first.ai_run_id) if first and first.ai_run_id else None
    return {"created_by": need.created_by, "source": _source(run), "rationale": first.rationale if first else None,
            "created_at": need.created_at}  # fmt: skip


def analysis(session: Session, r: Request) -> dict[str, Any] | None:
    if r.need_statement is None and r.extraction_rationale is None:
        return None  # not processed yet
    run = session.exec(
        select(AIRun)
        .where(AIRun.request_id == r.id, AIRun.step == "extract", AIRun.outcome == "ok")
        .order_by(col(AIRun.id).desc())
    ).first()
    return {"need_statement": r.need_statement, "problem": r.problem, "persona": r.persona,
            "job_to_be_done": r.job_to_be_done, "proposed_solution": r.proposed_solution,
            "product_area": r.product_area, "severity_signal": r.severity_signal,
            "confidence": r.extraction_confidence, "rationale": r.extraction_rationale, "source": _source(run)}  # fmt: skip


def link(session: Session, r: Request, need_id: int) -> dict[str, Any] | None:
    event = session.exec(
        select(LinkEvent)
        .where(
            LinkEvent.request_id == r.id, LinkEvent.need_id == need_id, LinkEvent.action == LinkAction.link
        )
        .order_by(col(LinkEvent.id).desc())
    ).first()
    if event is None:
        return None
    sug = session.get(AISuggestion, event.suggestion_id) if event.suggestion_id else None
    if sug is None:
        sug = session.exec(
            select(AISuggestion)
            .where(
                AISuggestion.request_id == r.id,
                AISuggestion.need_id == need_id,
                col(AISuggestion.state).in_([SuggestionState.applied, SuggestionState.accepted]),
            )
            .order_by(col(AISuggestion.id).desc())
        ).first()
    run = session.get(AIRun, sug.ai_run_id) if sug and sug.ai_run_id else None
    return {"actor": event.actor_id or str(event.actor), "at": event.created_at,
            "routing_score": event.routing_score if event.routing_score is not None else (sug.routing_score if sug else None),
            "label": sug.label if sug else None, "rationale": sug.rationale if sug else None, "source": _source(run)}  # fmt: skip


def evidence(session: Session, need: Need, member_ids: list[int]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for s in session.exec(
        select(AISuggestion).where(
            AISuggestion.need_id == need.id,
            col(AISuggestion.request_id).in_(member_ids),
            col(AISuggestion.state).in_([SuggestionState.applied, SuggestionState.accepted]),
        )
    ).all():
        out += [{"quote": q, "kind": "link", "request_id": s.request_id, "goal": None} for q in s.quotes]
    if need.fit_run_id is not None:
        for g in session.exec(select(GoalRating).where(GoalRating.ai_run_id == need.fit_run_id)).all():
            if g.quote:
                out.append({"quote": g.quote, "kind": "strategic_fit", "request_id": None, "goal": g.goal})
    return out


def updates(session: Session, need_id: int) -> list[dict[str, Any]]:
    rows = session.exec(
        select(StakeholderUpdate, Requester)
        .join(Requester, isouter=True)
        .where(
            StakeholderUpdate.need_id == need_id,
            StakeholderUpdate.status == "approved",
            StakeholderUpdate.kind == "requester_update",  # CS notes are internal: the PM view only
        )
        .order_by(col(StakeholderUpdate.approved_at).desc())
    ).all()
    return [{"id": u.id, "kind": u.kind, "requester_id": u.requester_id, "body": u.approved_body or u.body, "requester_name": p.name if p else None,
             "approved_at": u.approved_at} for u, p in rows]  # fmt: skip


def audit_trail(session: Session, need: Need, member_ids: list[int]) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for e in session.exec(select(LinkEvent).where(LinkEvent.need_id == need.id)).all():
        who = e.actor_id or str(e.actor)
        what = f"Request {e.request_id}" if e.request_id else f"Support {e.support_id}"
        score = f", routing score {e.routing_score:.2f}" if e.routing_score is not None else ""
        verb = "linked" if e.action == LinkAction.link else "unlinked"
        reason = f": {e.reason}" if e.reason else ""
        events.append({"at": e.created_at, "kind": str(e.action), "actor": who,
                       "summary": f"{what} {verb} by {e.actor}{score}{reason}", "request_id": e.request_id})  # fmt: skip
    for c in session.exec(select(NeedStatusChange).where(NeedStatusChange.need_id == need.id)).all():
        events.append({"at": c.created_at, "kind": "status", "actor": c.by,
                       "summary": f"Status {c.from_status} → {c.to_status}: {c.reason}" if c.reason
                       else f"Status {c.from_status} → {c.to_status}"})  # fmt: skip
    for s in session.exec(
        select(AISuggestion).where(AISuggestion.need_id == need.id, col(AISuggestion.decided_at).is_not(None))
    ).all():
        verdict = f"audit verdict {s.audit_verdict}" if s.audit_verdict else f"suggestion {s.state}"
        events.append({"at": s.decided_at, "kind": "decision", "actor": s.decided_by or "pm",
                       "summary": f"{verdict.capitalize()}", "request_id": s.request_id})  # fmt: skip
    mine = col(AIRun.need_id) == need.id
    runs = select(AIRun).where(or_(mine, col(AIRun.request_id).in_(member_ids)) if member_ids else mine)
    for run in session.exec(runs).all():
        events.append({"at": run.created_at, "kind": "ai_run", "actor": run.model, "model": run.model,
                       "summary": f"{run.step} ({run.prompt_version}): {run.outcome}, ${run.cost_usd:.4f}, {run.latency_ms} ms",
                       "request_id": run.request_id})  # fmt: skip
    events.sort(key=lambda e: _aware(e["at"]), reverse=True)
    return events
