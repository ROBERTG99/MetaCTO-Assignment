"""AI Ops and the success metrics (spec §10, F8), computed from the rows the app already writes.

Every number is derived on read from ai_runs, aisuggestion, linkevent, support and request: nothing here is
stored, and nothing is estimated. M3 comes from the status changes and the approvals of stakeholder updates (F7).
"""

import math
from collections import defaultdict
from datetime import UTC
from typing import Any

from sqlmodel import Session, select

from app.health import queue_stats
from app.models import (
    AIRun,
    AISuggestion,
    LinkAction,
    LinkActor,
    LinkEvent,
    NeedStatusChange,
    Request,
    RequestStatus,
    StakeholderUpdate,
    SuggestionKind,
    SuggestionState,
    Support,
)

FALSE_MERGE_TARGET = 0.03  # spec §10, M4
PM_MINUTES_PER_REQUEST = 2  # spec A6


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if n == 0:
        return (0.0, 1.0)
    p = k / n
    denom = 1 + z * z / n
    center = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return (max(0.0, center - half), min(1.0, center + half))


def rate(k: int, n: int) -> dict[str, Any]:
    low, high = wilson(k, n)
    return {"k": k, "n": n, "value": k / n if n else None, "low": low, "high": high}


def _pct(values: list[int], q: float) -> int:
    ordered = sorted(values)
    return ordered[max(1, math.ceil(q * len(ordered))) - 1] if ordered else 0


def _runs(session: Session) -> tuple[list[dict[str, Any]], int, float]:
    groups: dict[tuple[str, str, str], list[AIRun]] = defaultdict(list)
    runs = session.exec(select(AIRun)).all()
    for r in runs:
        groups[(r.step, r.model, r.prompt_version)].append(r)
    out = []
    for (step, model, version), rs in sorted(groups.items()):
        ok = sum(r.outcome == "ok" for r in rs)
        cost = sum(r.cost_usd for r in rs)
        lat = [r.latency_ms for r in rs]
        out.append({"step": step, "model": model, "prompt_version": version, "calls": len(rs), "ok": ok,
                    "failure_rate": (len(rs) - ok) / len(rs), "cost_usd": round(cost, 6),
                    "cost_per_call": cost / len(rs), "p50_ms": _pct(lat, 0.5), "p95_ms": _pct(lat, 0.95)})  # fmt: skip
    return out, len(runs), sum(r.cost_usd for r in runs)


def overview(session: Session) -> dict[str, Any]:
    runs, calls, cost = _runs(session)
    requests = session.exec(select(Request)).all()
    finished = [r for r in requests if r.status in (RequestStatus.processed, RequestStatus.needs_review)]
    failed = {r.id for r in finished if r.status == RequestStatus.needs_review}
    suggestions = session.exec(select(AISuggestion)).all()
    events = session.exec(select(LinkEvent)).all()

    decided = [s for s in suggestions if s.kind == SuggestionKind.duplicate and s.request_id is not None
               and s.decided_by and s.state in (SuggestionState.accepted, SuggestionState.rejected)]  # fmt: skip
    accepted = sum(s.state == SuggestionState.accepted for s in decided)

    audited = [s for s in suggestions if s.audit_sample and s.audit_verdict is not None]
    false_merges = sum(s.audit_verdict == "false_merge" for s in audited)
    audit_rate = rate(false_merges, len(audited))
    # An auto-link is a link by the policy with a routing score (new-need links have none).
    auto = {(e.request_id, e.need_id) for e in events
            if e.action == LinkAction.link and e.actor == LinkActor.auto and e.routing_score is not None}  # fmt: skip
    undone = {(e.request_id, e.need_id) for e in events
              if e.action == LinkAction.unlink and e.actor == LinkActor.pm} & auto  # fmt: skip

    pm_events = {e.request_id for e in events if e.actor == LinkActor.pm and e.request_id is not None}
    pm_decisions = {s.request_id for s in suggestions if s.request_id is not None and s.decided_by
                    and s.state in (SuggestionState.accepted, SuggestionState.rejected, SuggestionState.undone)}  # fmt: skip
    waiting = {  # a suggestion in the PM's inbox; "related" ones are informational and never decided
        s.request_id
        for s in suggestions
        if s.request_id is not None
        and s.state == SuggestionState.proposed
        and s.kind == SuggestionKind.duplicate
    }
    touched = pm_events | pm_decisions | waiting | failed
    untouched = sum(r.id not in touched for r in finished)

    claims = len(session.exec(select(Support.id)).all())
    new_need = {
        s.request_id: s.need_id for s in suggestions if s.kind == SuggestionKind.new_need and s.request_id
    }
    # A PM relink to an existing need carries no reason; _own_need's links (undo, false merge) always do.
    relinked = {
        e.request_id
        for e in events
        if e.action == LinkAction.link
        and e.actor == LinkActor.pm
        and not e.reason
        and e.request_id in new_need
        and e.need_id != new_need[e.request_id]
    }

    n = len(finished)
    return {
        "runs": runs,
        "totals": {
            "calls": calls,
            "cost_usd": round(cost, 6),
            "processed_requests": n,
            "cost_per_request": cost / n if n else None,
        },
        "acceptance": rate(accepted, len(decided)),
        "needs_review": rate(len(failed), n),
        "false_merge": {
            "audited": audit_rate,
            "target": FALSE_MERGE_TARGET,
            "within_target": audit_rate["high"] <= FALSE_MERGE_TARGET if audited else None,
            "auto_links": len(auto),
            "undone": len(undone),
            "undo_rate": len(undone) / len(auto) if auto else None,
        },
        "m1": {
            "processed": n,
            "untouched": untouched,
            "value": untouched / n if n else None,
            "pm_minutes_per_100": (n - untouched) / n * 100 * PM_MINUTES_PER_REQUEST if n else None,
        },
        "m2": {
            "claims": claims,
            "new_requests": len(requests),
            "deflection": claims / (claims + len(requests)) if claims + len(requests) else None,
            "new_need_requests": len(new_need),
            "relinked_by_pm": len(relinked),
            "leakage": len(relinked) / len(new_need) if new_need else None,
            "note": "Deflection counts every support (each starts as a claim at the door). Leakage needs a manual "
            "relink action, which the inbox doesn't have yet, so it stays 0 until one exists.",
        },
        "m3": _m3(session),
        "queue": queue_stats(session),
    }


def _m3(session: Session) -> dict[str, Any]:
    rows: dict[int, tuple[Any, list[tuple[str, Any]]]] = {}
    for c in session.exec(select(NeedStatusChange)).all():
        if c.id is not None:
            rows[c.id] = (c.created_at, [])
    for u in session.exec(
        select(StakeholderUpdate).where(StakeholderUpdate.kind == "requester_update")
    ).all():
        if u.status_change_id in rows:
            rows[u.status_change_id][1].append((u.status, u.approved_at))
    return m3_from(list(rows.values()))


def m3_from(changes: list[tuple[Any, list[tuple[str, Any]]]]) -> dict[str, Any]:
    """M3 decision-loop latency from (change time, [(personal update status, approved_at)]) per status change.

    A change is complete when every personal update that wasn't superseded or discarded is approved; its
    latency runs to the last approval. Discarded updates are supporters never told, counted apart so the
    median isn't flattered by them. Superseded drafts belong to a decision that was replaced.
    """
    latencies: list[float] = []
    pending = not_notified = 0
    for created_at, updates in changes:
        live = [(st, at) for st, at in updates if st not in ("superseded", "discarded")]
        not_notified += sum(st == "discarded" for st, _ in updates)
        if not live:
            continue
        if any(st == "draft" for st, _ in live):
            pending += 1
            continue
        last = max(_aware(at) for _, at in live if at is not None)
        latencies.append((last - _aware(created_at)).total_seconds())
    latencies.sort()
    n = len(latencies)
    median = (
        None if n == 0 else latencies[n // 2] if n % 2 else (latencies[n // 2 - 1] + latencies[n // 2]) / 2
    )
    return {"value": median, "completed": n, "pending": pending, "not_notified": not_notified,
            "note": "Median time from a need's status change to the PM approving the last supporter's personal "
            "update (every supporter notified). Pending changes still have drafts waiting; discarded updates are "
            "supporters never told."}  # fmt: skip


def _aware(t: Any) -> Any:
    return t if t.tzinfo else t.replace(tzinfo=UTC)
