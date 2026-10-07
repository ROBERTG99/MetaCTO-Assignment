"""Closing the loop (spec F7): a status change is a human decision; the AI drafts, code checks, the PM approves.

The status is saved first and drafting is a worker job on the NeedStatusChange row, so the decision never
waits on a model. Drafts reach the simulated outbox only through approve(), which re-runs the commitment
check and refuses while it flags anything. Approving a personal update marks that supporter notified.
"""

from dataclasses import asdict
from datetime import date
from typing import Any

from sqlalchemy import update
from sqlmodel import Session, col, select

from app.ai.commitments import check
from app.ai.pipeline import Deps
from app.errors import AppError, not_found
from app.models import (
    Account,
    AIRun,
    Need,
    NeedStatus,
    NeedStatusChange,
    Notification,
    OutboxMessage,
    Request,
    Requester,
    StakeholderUpdate,
    Support,
    SupportLinkStatus,
    utcnow,
)


def change_status(
    session: Session, need_id: int, status: str, reason: str, target_date: date | None, by: str
) -> NeedStatusChange:
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
    target = NeedStatus(status)
    if need.status == target:
        raise AppError(409, "no_change", f"Need {need_id} is already {target}")
    change = NeedStatusChange(need_id=need_id, from_status=need.status, to_status=target, by=by, reason=reason,
                              target_date=target_date, drafts_status="pending")  # fmt: skip
    need.status, need.updated_at = target, utcnow()
    session.add(need)
    _supersede(session, need_id)
    session.add(change)
    session.commit()
    session.refresh(change)
    return change


def _supersede(session: Session, need_id: int) -> None:
    """A new decision replaces the last one: its unsent drafts can't be sent, and a drafting job not yet run
    is skipped without a model call (a requester must never hear "planned" for a need now declined)."""
    for old in session.exec(select(NeedStatusChange).where(NeedStatusChange.need_id == need_id)).all():
        if old.drafts_status == "pending":
            old.drafts_status = "superseded"
            session.add(old)
    session.exec(
        update(StakeholderUpdate)
        .where(col(StakeholderUpdate.need_id) == need_id, col(StakeholderUpdate.status) == "draft")
        .values(status="superseded")
    )


def supporters(session: Session, need_id: int) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Who to tell: authors of member requests and confirmed supporters (a claim counts once confirmed), each
    once, with what they asked for; and every account they asked for (staff can file for several)."""
    asked: dict[int, list[str]] = {}
    accounts_of: dict[int, set[int]] = {}
    for r in session.exec(
        select(Request).where(Request.need_id == need_id).order_by(col(Request.created_at), col(Request.id))
    ).all():
        asked.setdefault(r.requester_id, []).append(r.title)
        if r.account_id is not None:
            accounts_of.setdefault(r.requester_id, set()).add(r.account_id)
    for sup in session.exec(
        select(Support).where(Support.need_id == need_id, Support.link_status == SupportLinkStatus.confirmed)
    ).all():
        asked.setdefault(sup.requester_id, []).append(sup.why_it_matters or "support for this need")
    people = {
        p.id: p for p in session.exec(select(Requester).where(col(Requester.id).in_(list(asked)))).all()
    }
    out: list[dict[str, Any]] = []
    by_account: dict[int, list[str]] = {}
    for rid in sorted(asked, key=lambda i: (people[i].name, i)):
        p = people[rid]
        out.append({"requester_id": rid, "name": p.name, "asked": "; ".join(asked[rid])[:ASKED_MAX]})
        for account_id in sorted(accounts_of.get(rid) or ({p.account_id} if p.account_id else set())):
            by_account.setdefault(account_id, []).append(p.name)
    names = {
        a.id: a.name for a in session.exec(select(Account).where(col(Account.id).in_(list(by_account)))).all()
    }
    accounts = [{"account_id": a, "name": names[a], "supporters": by_account[a]} for a in sorted(by_account)]
    return out, accounts


ASKED_MAX = 500  # characters of what each supporter asked for, so a busy need still fits one call


def _flags(body: str, target_date: date | None) -> list[dict[str, Any]]:
    return [asdict(f) for f in check(body, target_date)]


def process_drafts(session: Session, change_id: int, deps: Deps) -> str:
    change = session.get(NeedStatusChange, change_id)
    if change is None:
        raise ValueError(f"status change {change_id} not found")
    if change.drafts_status != "pending":
        return "done"
    if _latest(session, change.need_id) != change.id:  # a newer decision came first: no model call
        change.drafts_status = "superseded"
        session.add(change)
        session.commit()
        return "superseded"
    need = session.get(Need, change.need_id)
    assert need is not None
    people, accounts = supporters(session, change.need_id)
    if people:
        out, run_id = deps.gateway.draft_updates(
            need_title=need.title, need_problem=need.problem or need.title, status=str(change.to_status),
            reason=change.reason, target_date=change.target_date.isoformat() if change.target_date else None,
            supporters=people, accounts=accounts, need_id=need.id,
        )  # fmt: skip
        for u in out.requester_updates:
            session.add(StakeholderUpdate(need_id=change.need_id, status_change_id=change.id, kind="requester_update",
                                          requester_id=u.requester_id, body=u.body, original_body=u.body,
                                          flagged_commitments=_flags(u.body, change.target_date), ai_run_id=run_id))  # fmt: skip
        for n in out.cs_notes:
            session.add(StakeholderUpdate(need_id=change.need_id, status_change_id=change.id, kind="cs_note",
                                          account_id=n.account_id, body=n.body, original_body=n.body,
                                          flagged_commitments=_flags(n.body, change.target_date), ai_run_id=run_id))  # fmt: skip
    change.drafts_status, change.drafts_error = "drafted", None
    session.add(change)
    session.commit()
    return "drafted"


def _draft_out(session: Session, u: StakeholderUpdate) -> dict[str, Any]:
    who = session.get(Requester, u.requester_id) if u.requester_id else None
    account = session.get(Account, u.account_id) if u.account_id else None
    run = session.get(AIRun, u.ai_run_id) if u.ai_run_id else None
    return {"id": u.id, "kind": u.kind, "requester_id": u.requester_id, "requester_name": who.name if who else None,
            "account_id": u.account_id, "account_name": account.name if account else None, "body": u.body,
            "original_body": u.original_body, "edited": u.body != u.original_body, "flags": u.flagged_commitments,
            "status": u.status, "approved_by": u.approved_by, "approved_at": u.approved_at,
            "source": {"model": run.model, "prompt_version": run.prompt_version, "ai_run_id": run.id} if run else None}  # fmt: skip


def change_out(session: Session, c: NeedStatusChange, with_updates: bool = True) -> dict[str, Any]:
    rows = session.exec(
        select(StakeholderUpdate).where(StakeholderUpdate.status_change_id == c.id).order_by(col(StakeholderUpdate.id))
    ).all() if with_updates else []  # fmt: skip
    return {"id": c.id, "need_id": c.need_id, "from_status": c.from_status, "to_status": c.to_status, "by": c.by,
            "reason": c.reason, "target_date": c.target_date, "created_at": c.created_at,
            "drafts_status": c.drafts_status, "drafts_error": c.drafts_error,
            "updates": [_draft_out(session, u) for u in rows]}  # fmt: skip


def list_for_need(session: Session, need_id: int) -> dict[str, Any]:
    if session.get(Need, need_id) is None:
        raise not_found("Need", need_id)
    changes = session.exec(
        select(NeedStatusChange)
        .where(NeedStatusChange.need_id == need_id)
        .order_by(col(NeedStatusChange.created_at).desc(), col(NeedStatusChange.id).desc())
    ).all()
    return {"changes": [change_out(session, c) for c in changes]}


def _latest(session: Session, need_id: int) -> int | None:
    return session.exec(
        select(NeedStatusChange.id)
        .where(NeedStatusChange.need_id == need_id)
        .order_by(col(NeedStatusChange.id).desc())
    ).first()


def _get_draft(session: Session, update_id: int) -> tuple[StakeholderUpdate, NeedStatusChange | None]:
    u = session.get(StakeholderUpdate, update_id)
    if u is None:
        raise not_found("Update", update_id)
    if u.status != "draft":
        raise AppError(409, "not_draft", f"Update {update_id} is already {u.status}")
    change = session.get(NeedStatusChange, u.status_change_id) if u.status_change_id else None
    return u, change


def _while_draft(session: Session, update_id: int, **values: Any) -> None:
    """Compare-and-set: the write applies only while the row is a draft, so an edit can't land on an approved
    message and two approvals can't both send. The loser gets 409."""
    done = session.exec(
        update(StakeholderUpdate)
        .where(col(StakeholderUpdate.id) == update_id, col(StakeholderUpdate.status) == "draft")
        .values(**values)
    )
    if done.rowcount != 1:
        session.rollback()
        raise AppError(409, "not_draft", f"Update {update_id} was approved, discarded or replaced meanwhile")


def edit(session: Session, update_id: int, body: str, by: str) -> dict[str, Any]:
    u, change = _get_draft(session, update_id)
    flags = _flags(body, change.target_date if change else None)
    _while_draft(session, update_id, body=body, flagged_commitments=flags, edited_by=by, edited_at=utcnow())
    session.commit()
    session.refresh(u)
    return _draft_out(session, u)


def approve(session: Session, update_id: int, by: str) -> dict[str, Any]:
    """The only way out. Re-checks the text as approved; refuses while anything is flagged."""
    u, change = _get_draft(session, update_id)
    flags = _flags(u.body, change.target_date if change else None)
    if flags:
        _while_draft(session, update_id, flagged_commitments=flags)
        session.commit()
        raise AppError(409, "commitments_flagged", "Fix the flagged commitments before approving",
                       [{"field": "body", "issue": f["reason"]} for f in flags])  # fmt: skip
    now = utcnow()
    _while_draft(session, update_id, status="approved", approved_by=by, approved_at=now, approved_body=u.body)
    session.refresh(u)
    need = session.get(Need, u.need_id)
    title = need.title if need else f"need {u.need_id}"
    text = u.approved_body or u.body
    if u.kind == "requester_update" and u.requester_id is not None:
        who = session.get(Requester, u.requester_id)
        recipient = who.name if who else str(u.requester_id)
        session.add(OutboxMessage(update_id=u.id, channel="requester", recipient=recipient,  # type: ignore[arg-type]
                                  subject=f"Update on: {title}", body=text))  # fmt: skip
        session.add(Notification(need_id=u.need_id, requester_id=u.requester_id, update_id=u.id,  # type: ignore[arg-type]
                                 status_change_id=u.status_change_id, notified_at=now))  # fmt: skip
    else:
        account = session.get(Account, u.account_id) if u.account_id else None
        session.add(OutboxMessage(update_id=u.id, channel="cs", recipient=account.name if account else "CS",  # type: ignore[arg-type]
                                  subject=f"CS note: {title}", body=text))  # fmt: skip
    session.commit()
    return _draft_out(session, u)


def discard(session: Session, update_id: int, by: str) -> dict[str, Any]:
    u, _ = _get_draft(session, update_id)
    _while_draft(session, update_id, status="discarded", approved_by=by, approved_at=utcnow())
    session.commit()
    session.refresh(u)
    return _draft_out(session, u)


def redraft(session: Session, need_id: int, change_id: int) -> NeedStatusChange:
    """Draft again after a failure (the PM spends the call); only for the need's latest decision."""
    change = session.get(NeedStatusChange, change_id)
    if change is None or change.need_id != need_id:
        raise not_found("Status change", change_id)
    if change.drafts_status != "failed" or _latest(session, need_id) != change.id:
        raise AppError(409, "not_failed", f"Status change {change_id} isn't a failed, current drafting job")
    change.drafts_status, change.drafts_attempts, change.drafts_error = "pending", 0, None
    session.add(change)
    session.commit()
    session.refresh(change)
    return change


def outbox(session: Session) -> list[dict[str, Any]]:
    rows = session.exec(select(OutboxMessage).order_by(col(OutboxMessage.id).desc())).all()
    return [m.model_dump() for m in rows]
