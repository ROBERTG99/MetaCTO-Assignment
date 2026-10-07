"""Decision briefs as jobs (ADR 0007 pattern): a PM asks, the worker builds, the newest one is shown (F6)."""

import json
from typing import Any

from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, col, select

from app.ai import brief as briefing
from app.ai.pipeline import Deps
from app.errors import AppError, not_found
from app.models import AIRun, Brief, Need, NeedStatus, utcnow


def _need(session: Session, need_id: int) -> Need:
    need = session.get(Need, need_id)
    if need is None:
        raise not_found("Need", need_id)
    return need


def request_brief(session: Session, need_id: int, by: str) -> Brief:
    """Queue a brief. One already waiting for this need is returned instead, so a double click costs one."""
    need = _need(session, need_id)
    if need.status == NeedStatus.merged:
        raise AppError(409, "need_merged", f"Need {need_id} was merged; brief the need it went into")
    waiting = session.exec(
        select(Brief).where(Brief.need_id == need_id, col(Brief.status).in_(["pending", "processing"]))
    ).first()
    if waiting is not None:
        return waiting
    b = Brief(need_id=need_id, requested_by=by)
    session.add(b)
    try:
        session.commit()
    except (
        IntegrityError
    ):  # a concurrent request queued one first (the partial unique index): return that one
        session.rollback()
        waiting = session.exec(
            select(Brief).where(Brief.need_id == need_id, col(Brief.status).in_(["pending", "processing"]))
        ).first()
        if waiting is None:
            raise
        return waiting
    session.refresh(b)
    return b


def latest(session: Session, need_id: int) -> Brief:
    _need(session, need_id)
    b = session.exec(
        select(Brief)
        .where(Brief.need_id == need_id)
        .order_by(col(Brief.created_at).desc(), col(Brief.id).desc())
    ).first()
    if b is None:
        raise AppError(404, "no_brief", f"Need {need_id} has no brief yet")
    return b


def trace_id(brief_id: int) -> str:
    """The worker runs each brief job under this request ID, so every call behind it can be found (retries,
    repair rounds and failed attempts included), even when the brief itself failed."""
    return f"brief-{brief_id}"


def brief_out(session: Session, b: Brief, with_last_ready: bool = True) -> dict[str, Any]:
    assert b.id is not None
    runs = session.exec(select(AIRun).where(AIRun.trace_id == trace_id(b.id)).order_by(col(AIRun.id))).all()
    calls = [
        {"id": r.id, "step": r.step, "model": r.model, "prompt_version": r.prompt_version,
         "input_tokens": r.input_tokens, "output_tokens": r.output_tokens, "cache_read_tokens": r.cache_read_tokens,
         "cache_write_tokens": r.cache_write_tokens, "cost_usd": r.cost_usd, "latency_ms": r.latency_ms,
         "outcome": r.outcome}
        for r in runs
    ]  # fmt: skip
    return {"id": b.id, "need_id": b.need_id, "status": b.status, "requested_by": b.requested_by,
            "attempts": b.attempts, "error": b.error, "content": b.content, "calls": calls,
            "created_at": b.created_at, "finished_at": b.finished_at,
            "last_ready": _last_ready(session, b) if with_last_ready else None}  # fmt: skip


def _last_ready(session: Session, b: Brief) -> dict[str, Any] | None:
    """While a new brief builds or after it fails, the last good one stays reachable."""
    if b.status == "ready":
        return None
    ready = session.exec(
        select(Brief)
        .where(Brief.need_id == b.need_id, Brief.status == "ready")
        .order_by(col(Brief.created_at).desc(), col(Brief.id).desc())
    ).first()
    return brief_out(session, ready, with_last_ready=False) if ready else None


def process_brief(session: Session, brief_id: int, deps: Deps) -> None:
    """Build and store the brief. A failed brief call raises; the worker retries or fails the job."""
    b = session.get(Brief, brief_id)
    assert b is not None
    content = briefing.build(session, b.need_id, deps)
    b.status, b.content, b.error, b.finished_at = "ready", content, None, utcnow()
    session.add(b)
    session.commit()


def to_markdown(out: dict[str, Any], need_title: str) -> str:
    """The brief as a markdown page (docs/examples): what the product shows, including flags and how it was built."""
    c = out["content"]
    b, rel = c["brief"], c["related"]
    checks = {x["part"]: x for x in c["checks"]}

    def flag(part: str) -> str:
        x = checks.get(part)
        return f" **Unverified: {x['problem']}**" if x and not x["ok"] else ""

    def md(text: str) -> str:
        return " ".join(str(text).split()).replace("|", "\\|")

    lines = [f"# Decision brief: {need_title}", ""]
    verdict = (
        f"All {len(c['checks'])} claims checked against the data"
        if c["flagged"] == 0
        else f"{c['flagged']} of {len(c['checks'])} claims unverified, shown flagged"
    )
    lines += [
        f"Model: {c['model']} (prompt {c['prompt_version']}), confidence {b['confidence']:.2f}: "
        f"{b['confidence_rationale']}{flag('confidence_rationale')}",
        f"Verification: {verdict}{' after one repair round' if c['repaired'] else ''}.",
        "",
        "## Summary", "", b["summary"] + flag("summary"), "",
        "## Problem", "", b["problem"] + flag("problem"), "",
        "## Who is affected", "", b["who_is_affected"] + flag("who_is_affected"), "",
        "## Business impact", "",
    ]  # fmt: skip
    for i, x in enumerate(b["business_impact"]):
        facts = "; ".join(f"{f['label']}: {f['display']}" for f in x["facts"])
        lines.append(f"- {x['statement']}{f' ({facts})' if facts else ''}{flag(f'business_impact[{i}]')}")
    lines += ["", "## Evidence", ""]
    for i, e in enumerate(b["evidence"]):
        lines += [f"> {md(e['quote'])}", ">", f"> Request #{e['request_id']}{flag(f'evidence[{i}]')}", ""]
    lines += ["## Related needs", ""]
    if rel["status"] == "unavailable":
        lines.append(f"Not checked: {rel['reason']}")
    elif not b["related_needs"]:
        lines.append("None found in the backlog.")
    for i, r in enumerate(b["related_needs"]):
        title = r.get("need_title") or f"need #{r['need_id']}"
        lines.append(f"- {r['relation'].replace('_', ' ')}: {title} "
                     f"(need #{r['need_id']}). {r['why_it_matters']}{flag(f'related_needs[{i}]')}")  # fmt: skip
    if rel["status"] == "incomplete":
        lines.append(f"\n{rel['reason']}")
    lines += ["", "## Options", ""]
    for i, o in enumerate(b["options"]):
        lines.append(
            f"- **{o['name']}.** {o['description']} Tradeoffs: {o['tradeoffs']}{flag(f'options[{i}]')}"
        )
    lines += ["", "## Recommendation", "", b["recommendation"] + flag("recommendation"), "", "## Risks", ""]
    lines += [f"- {r}{flag(f'risks[{i}]')}" for i, r in enumerate(b["risks"])]
    lines += ["", "## Open questions", ""]
    lines += [f"- {q}{flag(f'open_questions[{i}]')}" for i, q in enumerate(b["open_questions"])]
    lines += [
        "", "## How this brief was built", "",
        f"1. **Overlap agent** ({rel['model']}, prompt {rel['prompt_version']}): {rel['tool_calls']} of {rel['cap']} "
        f"tool calls, read-only tools only; {rel['status']}{': ' + rel['reason'] if rel['reason'] else ''}.",
        "", "| # | Tool | Arguments | Result | Size | Latency |", "|---|---|---|---|---|---|",
    ]  # fmt: skip
    for st in rel["steps"]:
        lines.append(f"| {st['n']} | {st['tool']} | `{md(json.dumps(st['args']))}` | {st['status']} | "
                     f"{st['result_chars']} chars | {st['latency_ms']} ms |")  # fmt: skip
    lines += ["", "2. **Findings, checked in code** (a failing finding never reaches the brief):", ""]
    for f in rel["findings"]:
        mark = "verified" if f["verified"] else f"rejected: {f['problem']}"
        lines.append(f"- {f['relation']} need #{f['need_id']} ({f.get('need_title') or 'unknown'}), request "
                     f"#{f['request_id']}: \"{md(f['quote'])}\" ({mark})")  # fmt: skip
    if not rel["findings"]:
        lines.append("- none")
    total = sum(x["cost_usd"] for x in out["calls"])
    lines += [
        "", f"3. **Brief** ({c['model']}, prompt {c['prompt_version']}), then {len(c['checks'])} checks in code"
        f"{', one repair round' if c['repaired'] else ''}. Model calls (from ai_runs):", "",
        "| Run | Step | Model | Input | Cache write | Cache read | Output | Cost | Latency | Outcome |",
        "|---|---|---|---|---|---|---|---|---|---|",
    ]  # fmt: skip
    for x in out["calls"]:
        lines.append(f"| {x['id']} | {x['step']} | {x['model']} | {x['input_tokens']} | {x['cache_write_tokens']} | "
                     f"{x['cache_read_tokens']} | {x['output_tokens']} | ${x['cost_usd']:.4f} | {x['latency_ms']} ms | "
                     f"{x['outcome']} |")  # fmt: skip
    lines += ["", f"Total: {len(out['calls'])} calls, ${total:.4f}.", ""]
    return "\n".join(lines)
