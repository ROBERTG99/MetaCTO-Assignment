"""Decision briefs (spec F6, ADR 0001, ADR 0012): a workflow with one bounded agent step.

The brief's inputs are known in advance, so the brief itself is a workflow: gather the facts in code, make one
call on SMART_MODEL, verify the result in code. Only "what else in the backlog does this need overlap with,
block or depend on?" has a path that isn't known in advance; that is the related-needs agent's one job. The agent is
bounded (a cap of 8 tool calls and a wall-clock limit), read-only (three strict tools; anything else is
rejected unrun) and verifiable (every finding cites a request and a verbatim quote, checked here).
"""

import json
import logging
import re
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from datetime import date
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints
from sqlmodel import Session, col, func, select

from app.ai.gateway import TerminalError, ToolSpec, TransientError
from app.ai.pipeline import Deps, verify_quotes
from app.ai.redact import redact
from app.ai.schemas import DecisionBrief, RelatedFinding
from app.ai.schemas import RelatedNeeds as RelatedNeedsT
from app.models import Account, Need, NeedStatus, Request, Requester, Support, SupportLinkStatus
from app.services.priority import account_ids, breakdowns

log = logging.getLogger("distill.brief")

CAP = 8  # tool calls per run
MAX_BRIEF_REQUESTS = 25  # requests quoted to the brief; counts and money cover all of them
SEVERITY_RANK = {"blocker": 0, "important": 1, "nice_to_have": 2}
TIMEOUT_SECONDS = 90.0


def _schema(properties: dict[str, Any]) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": properties,
        "required": list(properties),
        "additionalProperties": False,
    }


TOOLS = [
    ToolSpec(
        "search_needs",
        "Search the backlog for needs similar to a text (embeddings). Returns up to 5 needs with id, title, "
        "persona, product area, status, request count and similarity. Read-only.",
        _schema({"query": {"type": "string", "description": "A problem or job, in plain words"}}),
    ),
    ToolSpec(
        "get_need",
        "Read one need: its problem, persona, product area, status and up to 8 of its requests with their "
        "ids and text. Read-only.",
        _schema({"need_id": {"type": "integer"}}),
    ),
    ToolSpec(
        "get_trend",
        "How demand for one need moved: requests and confirmed supports per month for the last 6 months, "
        "and the number of accounts. Read-only.",
        _schema({"need_id": {"type": "integer"}}),
    ),
]

StepStatus = Literal["ok", "rejected", "error", "budget"]


@dataclass
class Step:
    """One tool call in the trajectory: what was asked, what happened, how big the result was, how long."""

    n: int
    tool: str
    args: dict[str, Any]
    status: StepStatus
    result_chars: int
    latency_ms: int
    ai_run_id: int | None
    note: str | None = None


@dataclass
class Finding:
    need_id: int
    relation: str
    rationale: str
    request_id: int
    quote: str
    verified: bool
    problem: str | None = None
    need_title: str | None = None


@dataclass
class AgentResult:
    status: Literal["complete", "incomplete", "unavailable"]
    reason: str | None
    findings: list[Finding] = field(default_factory=list)
    steps: list[Step] = field(default_factory=list)
    run_ids: list[int] = field(default_factory=list)
    tool_calls: int = 0


class _Query(BaseModel):
    model_config = ConfigDict(extra="forbid")
    query: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=300)]


class _NeedRef(BaseModel):
    model_config = ConfigDict(extra="forbid")
    need_id: int = Field(ge=1)


def _json(obj: Any) -> str:
    """Tool results as JSON with accents and quotes as typed, so a quote the model copies matches the request."""
    return json.dumps(obj, ensure_ascii=False)


def _text(r: Request) -> str:
    """A request as the brief and the checks see it: title and description, redacted."""
    return redact(f"{r.title}\n{r.description}")


def _members(session: Session, need_id: int, limit: int | None = None) -> list[Request]:
    q = select(Request).where(Request.need_id == need_id).order_by(col(Request.created_at), col(Request.id))
    return list(session.exec(q.limit(limit) if limit else q).all())


def run_tool(session: Session, deps: Deps, target_id: int, name: str, args: dict[str, Any]) -> str:
    """Execute one read-only tool and return its result as JSON text. Bad arguments raise ValueError.
    Unknown tools are the caller's to reject: nothing here writes."""
    if name == "search_needs":
        query = _Query.model_validate(args).query
        hits = []
        for need_id, similarity in deps.search.search(query, k=6):
            n = session.get(Need, need_id)
            if n is None or n.id == target_id or n.status == NeedStatus.merged:
                continue
            count = session.exec(
                select(func.count()).select_from(Request).where(Request.need_id == n.id)
            ).one()
            hits.append({"need_id": n.id, "title": n.title, "persona": n.persona, "product_area": n.product_area,
                         "status": str(n.status), "requests": count, "similarity": round(similarity, 3)})  # fmt: skip
        return _json({"needs": hits[:5]})
    need_id = _NeedRef.model_validate(args).need_id
    n = session.get(Need, need_id)
    if n is None:
        raise ValueError(f"no need with id {need_id}")
    if name == "get_need":
        requests = [
            {"request_id": r.id, "title": r.title, "text": r.description}
            for r in _members(session, need_id, 8)
        ]
        return _json({"need_id": n.id, "title": n.title, "problem": n.problem, "persona": n.persona,
                           "product_area": n.product_area, "status": str(n.status), "requests": requests})  # fmt: skip
    if name == "get_trend":
        today = date.today()
        months = [
            f"{(today.year * 12 + today.month - 1 - i) // 12}-{(today.month - 1 - i) % 12 + 1:02d}"
            for i in range(5, -1, -1)
        ]
        made = [r.created_at.strftime("%Y-%m") for r in _members(session, need_id)]
        backed = [
            s.created_at.strftime("%Y-%m")
            for s in session.exec(select(Support).where(Support.need_id == need_id,
                                                        Support.link_status == SupportLinkStatus.confirmed)).all()
        ]  # fmt: skip
        trend = [{"month": m, "requests": made.count(m), "supports": backed.count(m)} for m in months]
        return _json({"need_id": need_id, "months": trend, "accounts": len(account_ids(session, need_id))})
    raise ValueError(f"unknown tool {name}")


def check_findings(session: Session, target_id: int, found: list[RelatedFinding]) -> list[Finding]:
    """A finding stands only if the need exists and is live, the request belongs to it, and the quote is in it."""
    out = []
    for f in found:
        need = session.get(Need, f.need_id)
        request = session.get(Request, f.request_id)
        problem = None
        if f.need_id == target_id:
            problem = "a need can't be related to itself"
        elif need is None:
            problem = f"need {f.need_id} does not exist"
        elif need.status == NeedStatus.merged:
            problem = f"need {f.need_id} was merged"
        elif request is None or request.need_id != f.need_id:
            problem = f"request {f.request_id} is not a request of need {f.need_id}"
        elif not verify_quotes([f.quote], _text(request))[0]:
            problem = f"the quote is not in request {f.request_id} verbatim"
        out.append(Finding(f.need_id, f.relation, f.rationale, f.request_id, f.quote, problem is None, problem,
                           need.title if need else None))  # fmt: skip
    return out


def _result(call_id: str, text: str, error: bool = False) -> dict[str, Any]:
    block: dict[str, Any] = {"type": "tool_result", "tool_use_id": call_id, "content": text}
    return {**block, "is_error": True} if error else block


def run_agent(
    session: Session,
    need: Need,
    deps: Deps,
    *,
    cap: int = CAP,
    timeout_seconds: float = TIMEOUT_SECONDS,
    clock: Callable[[], float] = time.monotonic,
) -> AgentResult:
    """The bounded loop. It never raises: a failure or a timeout is a result the brief reports."""
    assert need.id is not None
    allowed = {t.name for t in TOOLS}
    payload = {
        "title": need.title, "problem": need.problem, "persona": need.persona, "product_area": need.product_area,
        "requests": [{"request_id": r.id, "title": r.title, "text": r.description} for r in _members(session, need.id, 8)],
    }  # fmt: skip
    start = clock()
    transcript: list[dict[str, Any]] = []
    steps: list[Step] = []
    run_ids: list[int] = []
    calls, allow_tools, cut = 0, True, None
    while True:
        if clock() - start > timeout_seconds:
            return AgentResult(
                "unavailable", f"timed out after {timeout_seconds:g} s", [], steps, run_ids, calls
            )
        try:
            turn, run_id = deps.gateway.related_needs_turn(
                need=payload, transcript=transcript, tools=TOOLS, allow_tools=allow_tools, need_id=need.id
            )
        except (TransientError, TerminalError) as exc:
            return AgentResult("unavailable", str(exc), [], steps, run_ids, calls)
        except Exception as exc:  # a bug in a tool or the loop must not lose the brief
            return AgentResult(
                "unavailable", f"internal error: {type(exc).__name__}: {exc}", [], steps, run_ids, calls
            )
        run_ids.append(run_id)
        if not turn.tool_calls or not allow_tools:
            if not isinstance(turn.output, RelatedNeedsT):
                return AgentResult("incomplete", cut or "the agent gave no answer", [], steps, run_ids, calls)
            found = check_findings(session, need.id, turn.output.related)
            return AgentResult("incomplete" if cut else "complete", cut, found, steps, run_ids, calls)
        results = []
        for c in turn.tool_calls:
            n = len(steps) + 1
            if calls >= cap:
                steps.append(Step(n, c.name, c.input, "budget", 0, 0, run_id, f"over the cap of {cap} calls"))
                results.append(_result(c.id, f"Not run: the cap of {cap} tool calls is used up.", error=True))
                continue
            calls += 1
            started = time.perf_counter()
            status: StepStatus = "ok"
            note = None
            if c.name not in allowed:
                status, note = "rejected", "not one of the agent's tools"
                text = f"Unknown tool {c.name!r}. You can only use: {', '.join(sorted(allowed))} (all read-only)."
            else:
                try:
                    text = run_tool(session, deps, need.id, c.name, c.input)
                except ValueError as exc:  # pydantic's ValidationError included
                    status, note = "error", str(exc).splitlines()[0][:200]
                    text = f"Bad arguments: {note}"
                except Exception as exc:  # a failing tool is a step error, never a lost brief
                    log.exception("related-needs agent tool %s failed", c.name)
                    status, note = "error", f"{type(exc).__name__}: {exc}".splitlines()[0][:200]
                    text = f"The tool failed: {note}"
            ms = int((time.perf_counter() - started) * 1000)
            steps.append(Step(n, c.name, c.input, status, len(text), ms, run_id, note))
            results.append(_result(c.id, text, error=status != "ok"))
        transcript.append({"role": "assistant", "content": turn.content})
        if calls >= cap:
            allow_tools, cut = (
                False,
                f"Stopped at the cap of {cap} tool calls; related needs may be incomplete.",
            )
            results.append(
                {
                    "type": "text",
                    "text": f"You have used all {cap} tool calls. Answer now with what you found.",
                }
            )
        transcript.append({"role": "user", "content": results})


def _money(v: float) -> str:
    return f"${v:,.0f}"


def gather(session: Session, need: Need, deps: Deps) -> dict[str, Any]:
    """Everything the brief may cite, gathered in code: the need, its requests, accounts, scores and goals.
    facts maps a key to {label, value, display, kind}; money in the brief must equal one of these values."""
    assert need.id is not None
    members = _members(session, need.id)

    def weight(r: Request) -> tuple[int, int]:
        acct = session.get(Account, r.account_id) if r.account_id else None
        value = (acct.pipeline_value if acct and acct.is_prospect else acct.arr if acct else 0) or 0
        return (SEVERITY_RANK.get(r.severity_signal or "", 3), -value)

    shown = sorted(members, key=weight)[:MAX_BRIEF_REQUESTS]  # stable: older first within a rank
    requests = []
    for r in shown:
        who = session.get(Requester, r.requester_id)
        acct = session.get(Account, r.account_id) if r.account_id else None
        requests.append({"request_id": r.id, "title": r.title, "text": _text(r), "role": who.role if who else None,
                         "account": acct.name if acct else None, "segment": str(acct.segment) if acct else None})  # fmt: skip
    accounts = [
        a for i in sorted(account_ids(session, need.id)) if (a := session.get(Account, i)) is not None
    ]
    customers = [a for a in accounts if not a.is_prospect]
    prospects = [a for a in accounts if a.is_prospect]
    b = breakdowns(session, [need], deps.priorities)[need.id]
    supporters = session.exec(select(func.count()).select_from(Support).where(
        Support.need_id == need.id, Support.link_status == SupportLinkStatus.confirmed)).one()  # fmt: skip
    facts: dict[str, dict[str, Any]] = {}

    def fact(key: str, label: str, value: Any, display: str, kind: str = "count") -> None:
        facts[key] = {"label": label, "value": value, "display": display, "kind": kind}

    fact("requests", "Requests in this need", len(members), str(len(members)))
    fact("supporters", "Confirmed supporters", supporters, str(supporters))
    fact("accounts", "Accounts asking", len(accounts), str(len(accounts)))
    fact("customers", "Customer accounts", len(customers), str(len(customers)))
    fact("prospects", "Prospect accounts", len(prospects), str(len(prospects)))
    arr = sum(a.arr or 0 for a in customers)
    pipe = sum(a.pipeline_value or 0 for a in prospects)
    fact("arr_customers", "ARR of the customer accounts asking", arr, _money(arr), "money")
    fact("pipeline_prospects", "Pipeline of the prospect accounts asking", pipe, _money(pipe), "money")
    for a in customers:
        fact(f"account_{a.id}_arr", f"{a.name} ARR ({a.segment})", a.arr or 0, _money(a.arr or 0), "money")
    for a in prospects:
        fact(f"account_{a.id}_pipeline", f"{a.name} pipeline ({a.segment})", a.pipeline_value or 0,
             _money(a.pipeline_value or 0), "money")  # fmt: skip
    renewing = b.urgency.renewing_accounts
    fact("renewals_90d", "Customer accounts renewing within 90 days", len(renewing),
         f"{len(renewing)} ({', '.join(renewing) or 'none'})")  # fmt: skip
    fact(
        "max_severity",
        "Highest severity asked",
        b.urgency.max_severity,
        b.urgency.max_severity or "unknown",
        "label",
    )
    fact("priority", "Priority score (0-100)", round(b.priority, 1), f"{b.priority:.1f} / 100", "score")
    fact("demand", "Demand (0-1)", round(b.demand.value, 2), f"{b.demand.value:.2f}", "score")
    fact("urgency", "Urgency (0-1)", round(b.urgency.value, 2), f"{b.urgency.value:.2f}", "score")
    s = b.strategic.value
    fact("strategic_fit", "Strategic fit (0-1)", None if s is None else round(s, 2),
         "not rated" if s is None else f"{s:.2f}", "score")  # fmt: skip
    for g in b.strategic.goals:
        if g.rating is not None:
            fact(
                f"goal_{g.goal}",
                f"Rating for goal {g.title} (0-3)",
                g.rating,
                f"{g.rating} of 3: {g.rationale or ''}",
                "score",
            )
    fact("quadrant", "Quadrant", b.quadrant, (b.quadrant or "not rated").replace("_", " "), "label")
    need_out = {"title": need.title, "problem": need.problem, "persona": need.persona,
                "job_to_be_done": need.job_to_be_done, "product_area": need.product_area, "status": str(need.status)}  # fmt: skip
    return {"need": need_out, "requests": requests, "facts": facts, "goals": deps.priorities.goals}


MONEY = re.compile(r"\$\s?(\d[\d,]*(?:\.\d+)?)(?:\s?(k|m|bn|b|million|thousand|billion)\b)?", re.I)
SCALED = re.compile(
    r"(?<![$\d.,])\b(\d[\d,]*(?:\.\d+)?)\s?(k|m|million|thousand)\s+(?:in\s+|of\s+)?(?:arr|pipeline|revenue)\b",
    re.I,
)
SCALE = {"k": 1e3, "thousand": 1e3, "m": 1e6, "million": 1e6, "b": 1e9, "bn": 1e9, "billion": 1e9}
REMOVED = "[figure removed: not in the data]"


def _figures(text: str) -> list[tuple[int, int, str, float, bool]]:
    """(start, end, text, value, scaled) for each money figure written in the text."""
    out = []
    for m in [*MONEY.finditer(text), *SCALED.finditer(text)]:
        unit = (m.group(2) or "").lower()
        value = float(m.group(1).replace(",", "")) * SCALE.get(unit, 1)
        out.append((m.start(), m.end(), m.group(0), value, bool(unit)))
    kept: list[tuple[int, int, str, float, bool]] = []
    for f in sorted(out):  # "$ 900k ARR" matches both patterns: keep the first, drop overlaps
        if not kept or f[0] >= kept[-1][1]:
            kept.append(f)
    return kept


def _unverified(text: str, money: list[float]) -> list[tuple[int, int, str]]:
    bad = []
    for start, end, shown, value, scaled in _figures(text):
        ok = any(abs(value - f) <= (0.05 * f if scaled else 1.0) for f in money)
        if not ok:
            bad.append((start, end, shown))
    return bad


def _prose(b: DecisionBrief) -> list[tuple[str, str]]:
    parts = [("summary", b.summary), ("problem", b.problem), ("who_is_affected", b.who_is_affected),
             ("recommendation", b.recommendation), ("confidence_rationale", b.confidence_rationale)]  # fmt: skip
    parts += [(f"business_impact[{i}]", c.statement) for i, c in enumerate(b.business_impact)]
    parts += [(f"related_needs[{i}]", r.why_it_matters) for i, r in enumerate(b.related_needs)]
    parts += [(f"options[{i}]", f"{o.name}\n{o.description}\n{o.tradeoffs}") for i, o in enumerate(b.options)]
    parts += [(f"risks[{i}]", r) for i, r in enumerate(b.risks)]
    parts += [(f"open_questions[{i}]", q) for i, q in enumerate(b.open_questions)]
    return parts


def check_brief(
    brief: DecisionBrief, facts: dict[str, dict[str, Any]], texts: dict[int, str], related_ids: set[int]
) -> list[dict[str, Any]]:
    """One check per claim: {part, ok, problem}. Code decides what holds; the model only proposes."""
    money = [float(f["value"]) for f in facts.values() if f["kind"] == "money"]
    problems: dict[str, list[str]] = {}
    for part, text in _prose(brief):
        problems[part] = [
            f"the figure {shown} is not in the data" for _s, _e, shown in _unverified(text, money)
        ]
    for i, c in enumerate(brief.business_impact):
        unknown = [k for k in c.fact_keys if k not in facts]
        if unknown:
            problems[f"business_impact[{i}]"].append(f"unknown fact keys: {', '.join(unknown)}")
    for i, e in enumerate(brief.evidence):
        if e.request_id not in texts:
            problems[f"evidence[{i}]"] = [f"request {e.request_id} is not one of this need's requests"]
        elif not verify_quotes([e.quote], texts[e.request_id])[0]:
            problems[f"evidence[{i}]"] = [f"the quote is not in request {e.request_id} verbatim"]
        else:
            problems[f"evidence[{i}]"] = []
    for i, r in enumerate(brief.related_needs):
        if r.need_id not in related_ids:
            problems[f"related_needs[{i}]"].append(f"need {r.need_id} is not a verified related need")
    return [{"part": p, "ok": not ps, "problem": "; ".join(ps) or None} for p, ps in problems.items()]


def _render(
    brief: DecisionBrief,
    facts: dict[str, dict[str, Any]],
    titles: dict[int, str],
    checks: list[dict[str, Any]],
) -> dict[str, Any]:
    """The brief as stored: figures that aren't in the data are removed from the prose and from quotes that
    failed their check (a verified quote is the requester's own text); impact claims carry the cited values."""
    money = [float(f["value"]) for f in facts.values() if f["kind"] == "money"]

    def clean(text: str) -> str:
        for start, end, _shown in reversed(_unverified(text, money)):
            text = text[:start] + REMOVED + text[end:]
        return text

    out = brief.model_dump()
    for key in ("summary", "problem", "who_is_affected", "recommendation", "confidence_rationale"):
        out[key] = clean(out[key])
    out["risks"] = [clean(r) for r in out["risks"]]
    out["open_questions"] = [clean(q) for q in out["open_questions"]]
    for o in out["options"]:
        o.update({k: clean(o[k]) for k in ("name", "description", "tradeoffs")})
    for r in out["related_needs"]:
        r["why_it_matters"] = clean(r["why_it_matters"])
        r["need_title"] = titles.get(r["need_id"])
    failed = {c["part"] for c in checks if not c["ok"]}
    for i, e in enumerate(out["evidence"]):
        if f"evidence[{i}]" in failed:
            e["quote"] = clean(e["quote"])
    for c in out["business_impact"]:
        c["statement"] = clean(c["statement"])
        c["facts"] = [{"key": k, "label": facts[k]["label"], "display": facts[k]["display"]}
                      for k in c["fact_keys"] if k in facts]  # fmt: skip
    return out


def build(
    session: Session, need_id: int, deps: Deps, *, clock: Callable[[], float] = time.monotonic
) -> dict[str, Any]:
    """The brief's stored content: the verified brief, its facts, checks, the agent's result and trajectory.
    Raises only if the brief call itself fails (the worker retries or fails the job with the reason)."""
    need = session.get(Need, need_id)
    assert need is not None and need.id is not None
    data = gather(session, need, deps)
    agent = run_agent(session, need, deps, clock=clock)
    verified = [f for f in agent.findings if f.verified]
    status = agent.status if agent.status == "complete" else f"{agent.status}: {agent.reason}"
    related = [asdict(f) for f in verified]
    texts = {int(r["request_id"]): str(r["text"]) for r in data["requests"]}
    ask = dict(need=data["need"], facts=data["facts"], requests=data["requests"], related=related,
               goals=data["goals"], related_status=status, need_id=need.id)  # fmt: skip
    brief, run_id = deps.gateway.decision_brief(**ask)
    runs = [*agent.run_ids, run_id]
    ids = {f.need_id for f in verified}
    checks = check_brief(brief, data["facts"], texts, ids)
    failing = [c for c in checks if not c["ok"]]
    repaired, repair_error = False, None
    if failing:  # one repair round; whatever still fails is shown flagged
        repair = "\n".join(f"{c['part']}: {c['problem']}" for c in failing)
        try:
            second, run_id = deps.gateway.decision_brief(**ask, repair=repair)
        except (TransientError, TerminalError) as exc:  # the first brief is still usable: keep it, flagged
            repair_error = str(exc)
        else:
            runs.append(run_id)
            again = check_brief(second, data["facts"], texts, ids)
            if sum(not c["ok"] for c in again) <= len(failing):  # keep the version with fewer failing claims
                brief, checks, repaired = second, again, True
    titles = {f.need_id: f.need_title or "" for f in verified}
    steps = deps.gateway.steps
    return {
        "brief": _render(brief, data["facts"], titles, checks),
        "facts": data["facts"],
        "checks": checks,
        "flagged": sum(not c["ok"] for c in checks),
        "repaired": repaired,
        "repair_error": repair_error,
        "related": {
            "status": agent.status,
            "reason": agent.reason,
            "cap": CAP,
            "tool_calls": agent.tool_calls,
            "findings": [asdict(f) for f in agent.findings],
            "steps": [asdict(x) for x in agent.steps],
            "model": steps["related_needs"].model,
            "prompt_version": "related_needs_v1",
        },
        "runs": runs,
        "model": steps["decision_brief"].model,
        "prompt_version": "decision_brief_v1",
    }
