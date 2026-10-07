"""The only module that talks to a model provider (CLAUDE.md rule 5).

Callers ask for a step (extract, adjudicate). The gateway renders the versioned prompt, redacts the text,
calls the configured client, validates the output with Pydantic, handles refusals, max_tokens and
validation repair, maps provider failures to TransientError or TerminalError, and writes one AIRun per call.
"""

import html
import json
import re
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, ClassVar, Protocol, TypeVar, runtime_checkable

from pydantic import BaseModel, ValidationError

from app.ai.redact import redact
from app.ai.schemas import (
    Adjudication,
    BriefOption,
    BriefRelatedNeed,
    CandidateNeed,
    CsNote,
    DecisionBrief,
    EvidenceQuote,
    Extraction,
    FitRating,
    ImpactClaim,
    ProductArea,
    RelatedFinding,
    RelatedNeeds,
    RequesterUpdate,
    StrategicFit,
    UpdateDrafts,
)
from app.models import AIRun
from app.observability import request_id as current_request_id
from app.scoring import Goal

T = TypeVar("T", bound=BaseModel)


class TransientError(Exception):
    """Timeout, 5xx, rate limit, connection: retry later. Never fails the submission."""


class TerminalError(Exception):
    """Refusal, repeated bad output, max_tokens twice, a 4xx: the request goes to needs_review."""


class Refused(Exception):
    def __init__(self, category: str | None = None, usage: "Usage | None" = None) -> None:
        super().__init__(f"refused ({category or 'no category'})")
        self.category, self.usage = category, usage


class MaxTokens(Exception):
    def __init__(self, usage: "Usage | None" = None) -> None:
        super().__init__("max_tokens")
        self.usage = usage


class BadOutput(Exception):
    """The model's output didn't validate against the schema."""

    def __init__(self, message: str, usage: "Usage | None" = None) -> None:
        super().__init__(message)
        self.usage = usage


@dataclass(frozen=True)
class Usage:
    input_tokens: int  # uncached input only, as the API reports it
    output_tokens: int
    cache_read_input_tokens: int = 0
    cache_creation_input_tokens: int = 0


@dataclass(frozen=True)
class Reply:
    output: BaseModel
    usage: Usage
    model: str


@dataclass(frozen=True)
class ToolCall:
    id: str
    name: str
    input: dict[str, Any]


@dataclass(frozen=True)
class ToolSpec:
    """A client tool the agent may call. Always sent with strict: true (schemas forbid extra properties)."""

    name: str
    description: str
    input_schema: dict[str, Any]


@dataclass(frozen=True)
class Turn:
    """One agent turn: the tools the model asked for, or its final answer once it stopped asking."""

    tool_calls: list[ToolCall]
    output: BaseModel | None
    content: list[dict[str, Any]]  # the assistant content, sent back unchanged on the next turn
    usage: Usage
    model: str
    stop_reason: str


class LLMClient(Protocol):
    name: str

    def complete(
        self,
        *,
        step: str,
        model: str,
        system: str,
        user: str,
        schema: type[BaseModel],
        max_tokens: int,
        effort: str | None,
        inputs: dict[str, Any],
        cache: bool = False,
    ) -> Reply: ...


@runtime_checkable
class ToolClient(LLMClient, Protocol):
    """A client that can also run agent turns with tools. The eval replay clients don't need to."""

    def converse(
        self,
        *,
        step: str,
        model: str,
        system: str,
        messages: list[dict[str, Any]],
        tools: list[ToolSpec],
        schema: type[BaseModel],
        max_tokens: int,
        allow_tools: bool,
        inputs: dict[str, Any],
    ) -> Turn: ...


@dataclass
class FakeCall:
    step: str
    model: str
    system: str
    user: str
    inputs: dict[str, Any]
    max_tokens: int


Outcome = BaseModel | Exception | list[ToolCall]  # a list of tool calls is an agent turn that uses tools
Responder = Callable[[dict[str, Any]], Outcome]


class FakeLLM:
    """Test double (CLAUDE.md rule 8). Scripted outcomes per step, in order; then a responder; then a default.

    Records exactly what it received, so tests can assert on redaction and prompts.
    """

    name = "fake"

    def __init__(self) -> None:
        self.calls: list[FakeCall] = []
        self.turns: list[dict[str, Any]] = []  # converse() arguments, for asserting on tools and messages
        self._scripts: dict[str, list[Outcome]] = {}
        self._responders: dict[str, Responder] = {}

    def script(self, step: str, *outcomes: Outcome) -> None:
        self._scripts.setdefault(step, []).extend(outcomes)

    def respond(self, step: str, fn: Responder) -> None:
        self._responders[step] = fn

    def complete(
        self,
        *,
        step: str,
        model: str,
        system: str,
        user: str,
        schema: type[BaseModel],
        max_tokens: int,
        effort: str | None,
        inputs: dict[str, Any],
        cache: bool = False,
    ) -> Reply:
        self.calls.append(FakeCall(step, model, system, user, inputs, max_tokens))
        outcome = self._next(step, inputs)
        if isinstance(outcome, Exception):
            raise outcome
        if isinstance(outcome, list):
            raise ValueError(f"{step}: tool calls scripted for a single call")
        return Reply(outcome, Usage(input_tokens=len(system + user) // 4, output_tokens=60), model)

    def converse(
        self,
        *,
        step: str,
        model: str,
        system: str,
        messages: list[dict[str, Any]],
        tools: list[ToolSpec],
        schema: type[BaseModel],
        max_tokens: int,
        allow_tools: bool,
        inputs: dict[str, Any],
    ) -> Turn:
        sent = json.dumps(messages, default=str)
        self.calls.append(FakeCall(step, model, system, sent, inputs, max_tokens))
        self.turns.append({"step": step, "system": system, "messages": messages, "tools": tools,
                           "allow_tools": allow_tools, "schema": schema})  # fmt: skip
        outcome = self._next(step, inputs)
        if isinstance(outcome, Exception):
            raise outcome
        usage = Usage(input_tokens=len(system + sent) // 4, output_tokens=40)
        if isinstance(outcome, list):
            content = [{"type": "tool_use", "id": c.id, "name": c.name, "input": c.input} for c in outcome]
            return Turn(outcome, None, content, usage, model, "tool_use")
        content = [{"type": "text", "text": outcome.model_dump_json()}]
        return Turn([], outcome, content, usage, model, "end_turn")

    def _next(self, step: str, inputs: dict[str, Any]) -> Outcome:
        if self._scripts.get(step):
            return self._scripts[step].pop(0)
        if step in self._responders:
            return self._responders[step](inputs)
        return self._default(step, inputs)

    @staticmethod
    def _default(step: str, inputs: dict[str, Any]) -> Outcome:
        if step == "extract":
            title = str(inputs.get("text", "")).split("\n")[0][:120] or "A need"
            return Extraction(
                need_statement=title, problem=title, persona="analyst", job_to_be_done=title,
                proposed_solution=title, product_area="other", severity_signal="unknown",
                evidence=[], confidence=0.5, rationale="fake",
            )  # fmt: skip
        if step == "adjudicate":
            return Adjudication(judgments=[])  # no judgment means "different" for every candidate
        if step == "stakeholder_update":
            return UpdateDrafts(
                requester_updates=[RequesterUpdate(requester_id=x["requester_id"], body=f"Update on {x['asked']}.")
                                   for x in inputs["supporters"]],
                cs_notes=[CsNote(account_id=a["account_id"], body=f"{a['name']}: status changed.") for a in inputs["accounts"]],
            )  # fmt: skip
        if step == "related_needs":
            return RelatedNeeds(related=[])
        if step == "decision_brief":
            first = inputs["requests"][0] if inputs.get("requests") else None
            return DecisionBrief(
                summary="Fake brief.", problem=str(inputs["need"]["problem"]), who_is_affected="The requesters.",
                business_impact=[], related_needs=[], options=[], recommendation="Decide.", confidence=0.5,
                confidence_rationale="fake", risks=[], open_questions=[],
                evidence=[EvidenceQuote(request_id=first["request_id"], quote=first["text"][:40])] if first else [],
            )  # fmt: skip
        if step == "strategic_fit":
            return StrategicFit(
                ratings=[
                    FitRating(goal=g["key"], rating=1, rationale="fake", quote="") for g in inputs["goals"]
                ]
            )
        raise ValueError(f"no default for step {step}")


@dataclass(frozen=True)
class StepConfig:
    model: str
    max_tokens: int
    effort: str | None = None
    cache: bool = False  # mark the system prompt cacheable; only worth it above the model's minimum prefix


Recorder = Callable[[AIRun], int]
PROMPTS = Path(__file__).resolve().parent / "prompts"
PROMPT_FOR_STEP = {
    "extract": "extract_need_v1",
    "adjudicate": "adjudicate_v1",
    "strategic_fit": "strategic_fit_v1",
    "stakeholder_update": "stakeholder_update_v1",
    "related_needs": "related_needs_v1",
    "decision_brief": "decision_brief_v1",
}
Check = Callable[[BaseModel], str | None]  # a problem the schema can't express, or None
PLACEHOLDER = re.compile(r"\{\{(\w+)\}\}")


@dataclass(frozen=True)
class Prompt:
    version: str
    system: str
    user: str

    @classmethod
    def load(cls, name: str, folder: Path = PROMPTS) -> "Prompt":
        text = (folder / f"{name}.md").read_text(encoding="utf-8")
        _header, rest = text.split("<!-- system -->", 1)
        system, user = rest.split("<!-- user -->", 1)
        return cls(version=name, system=system.strip(), user=user.strip())

    def render(self, values: dict[str, str]) -> str:
        """One pass over the template, so "{{candidates}}" typed by a user stays literal text."""
        return PLACEHOLDER.sub(lambda m: values.get(m.group(1), ""), self.user)


def _data(text: str) -> str:
    """Untrusted text as data: redacted, then escaped so it can't close or open our tags."""
    return html.escape(redact(text), quote=False)


def _attr(text: str) -> str:
    """Untrusted text inside an XML attribute: quotes are escaped too."""
    return html.escape(redact(text), quote=True)


def _scrub(value: Any) -> Any:
    if isinstance(value, str):
        return redact(value)
    if isinstance(value, list):
        return [_scrub(v) for v in value]
    if isinstance(value, dict):
        return {k: _scrub(v) for k, v in value.items()}
    return value


def _scrub_turn(message: dict[str, Any]) -> dict[str, Any]:
    """Agent transcript: tool results carry backlog text, so they are data (redacted, escaped). Our own text
    blocks and the model's assistant content pass unchanged."""
    if message["role"] != "user" or not isinstance(message["content"], list):
        return message
    blocks = [
        {**b, "content": _data(str(b["content"]))} if b.get("type") == "tool_result" else b
        for b in message["content"]
    ]
    return {**message, "content": blocks}


def _why_block(why: str | None) -> str:
    return f"<why_it_matters>\n{_data(why)}\n</why_it_matters>" if why and why.strip() else ""


@dataclass
class Gateway:
    client: LLMClient
    steps: dict[str, StepConfig]
    prices: dict[str, dict[str, float]]
    record: Recorder
    prompt_dir: Path = PROMPTS
    _prompts: dict[str, Prompt] = field(default_factory=dict)

    def extract(
        self, *, text: str, why: str | None, role: str | None, request_id: int | None = None
    ) -> tuple[Extraction, int]:
        values = {"role": _data(role or "unknown"), "text": _data(text), "why_block": _why_block(why)}
        inputs = {"text": text, "why": why, "role": role}
        out, run_id = self._call("extract", Extraction, values, inputs, request_id)
        assert isinstance(out, Extraction)
        return out, run_id

    def adjudicate(
        self,
        *,
        text: str,
        why: str | None,
        candidates: list[CandidateNeed],
        request_id: int | None = None,
        role: str | None = None,
        extracted: str | None = None,
    ) -> tuple[Adjudication, int]:
        blocks = []
        for c in candidates:
            examples = "".join(f"\n- {_data(e)}" for e in c.examples[:2])
            blocks.append(
                f'<candidate id="{html.escape(c.id)}">\ntitle: {_data(c.title)}\nproblem: {_data(c.problem)}\n'
                f"persona: {_data(c.persona or 'unknown')}\nproduct_area: {c.product_area or 'unknown'}\n"
                f"examples:{examples or ' none'}\n</candidate>"
            )
        values = {
            "role": _data(role or "unknown"),
            "text": _data(text),
            "why_block": _why_block(why),
            "extracted": _data(extracted or "not available"),
            "candidates": "\n".join(blocks),
        }
        inputs = {"text": text, "why": why, "role": role, "extracted": extracted,
                  "candidates": [c.model_dump() for c in candidates]}  # fmt: skip
        out, run_id = self._call("adjudicate", Adjudication, values, inputs, request_id)
        assert isinstance(out, Adjudication)
        return out, run_id

    def rate_fit(
        self,
        *,
        title: str,
        problem: str,
        persona: str | None,
        job_to_be_done: str | None,
        requests: list[str],
        goals: Sequence[Goal],
        need_id: int | None = None,
    ) -> tuple[StrategicFit, int]:
        """Rate one need against each goal. Who asked is not a parameter: fit is judged on the problem."""
        goal_blocks = "\n".join(
            f'<goal key="{html.escape(g.key)}">\ntitle: {html.escape(g.title)}\n'
            f"description: {html.escape(g.description)}\n</goal>"
            for g in goals
        )
        need = (
            f"title: {_data(title)}\nproblem: {_data(problem)}\npersona: {_data(persona or 'unknown')}\n"
            f"job_to_be_done: {_data(job_to_be_done or 'unknown')}"
        )
        texts = "\n".join(f'<request n="{i}">\n{_data(t)}\n</request>' for i, t in enumerate(requests, 1))
        values = {"goals": goal_blocks, "need": need, "requests": texts or "none yet"}
        inputs = {
            "need": {
                "title": title,
                "problem": problem,
                "persona": persona,
                "job_to_be_done": job_to_be_done,
            },
            "requests": requests,
            "goals": [{"key": g.key, "title": g.title, "description": g.description} for g in goals],
        }
        keys = [g.key for g in goals]

        def every_goal_once(out: BaseModel) -> str | None:
            assert isinstance(out, StrategicFit)
            got = [r.goal for r in out.ratings]
            if sorted(got) != sorted(keys):
                return f"rate each of these goals exactly once: {', '.join(keys)} (got: {', '.join(got) or 'none'})"
            return None

        out, run_id = self._call(
            "strategic_fit", StrategicFit, values, inputs, None, need_id, every_goal_once
        )
        assert isinstance(out, StrategicFit)
        return out, run_id

    def draft_updates(
        self,
        *,
        need_title: str,
        need_problem: str,
        status: str,
        reason: str,
        target_date: str | None,
        supporters: list[dict[str, Any]],
        accounts: list[dict[str, Any]],
        need_id: int | None = None,
    ) -> tuple[UpdateDrafts, int]:
        """Draft one personal update per supporter and one CS note per account. Drafts only: a PM approves."""
        decision = (
            f"new status: {html.escape(status)}\nreason (the PM's words): {_data(reason)}\n"
            f"target date: {html.escape(target_date) if target_date else 'none set'}"
        )
        need = f"title: {_data(need_title)}\nproblem: {_data(need_problem)}"
        people = "\n".join(
            f'<supporter id="{x["requester_id"]}" name="{_attr(x["name"])}">\n{_data(x["asked"])}\n</supporter>'
            for x in supporters
        )
        firms = "\n".join(
            f'<account id="{a["account_id"]}" name="{_attr(a["name"])}">supporters: '
            f"{_data(', '.join(a['supporters']))}</account>"
            for a in accounts
        )
        values = {"decision": decision, "need": need, "supporters": people, "accounts": firms}
        inputs = {"need": {"title": need_title, "problem": need_problem}, "status": status, "reason": reason,
                  "target_date": target_date, "supporters": supporters, "accounts": accounts}  # fmt: skip
        want_people = sorted(x["requester_id"] for x in supporters)
        want_firms = sorted(a["account_id"] for a in accounts)

        def everyone_once(out: BaseModel) -> str | None:
            assert isinstance(out, UpdateDrafts)
            got_people = sorted(u.requester_id for u in out.requester_updates)
            got_firms = sorted(n.account_id for n in out.cs_notes)
            if got_people != want_people or got_firms != want_firms:
                return (
                    f"write exactly one requester update for each supporter id {want_people} and one CS note "
                    f"for each account id {want_firms} (got {got_people} and {got_firms})"
                )
            return None

        # about 120 output tokens per message, with headroom; a max_tokens stop still gets one retry at double
        limit = max(
            self.steps["stakeholder_update"].max_tokens, 400 + 160 * (len(supporters) + len(accounts))
        )
        out, run_id = self._call(
            "stakeholder_update",
            UpdateDrafts,
            values,
            inputs,
            None,
            need_id,
            everyone_once,
            min(limit, 16_000),
        )
        assert isinstance(out, UpdateDrafts)
        return out, run_id

    def related_needs_turn(
        self,
        *,
        need: dict[str, Any],
        transcript: list[dict[str, Any]],
        tools: list[ToolSpec],
        allow_tools: bool,
        need_id: int | None = None,
    ) -> tuple[Turn, int]:
        """One turn of the overlap agent: recorded, redacted, refusals and limits mapped like any call.

        The first message (the need) is rendered here; transcript holds the turns since. Tool results carry
        backlog text, so they are redacted and escaped like any input; assistant content goes back unchanged.
        """
        step = "related_needs"
        prompt, cfg = self._prompt(step), self.steps[step]
        self._price(step, cfg.model)
        client = self.client
        if not isinstance(client, ToolClient):
            raise TerminalError(f"{step}: the {client.name} client can't run tools")
        requests = "\n".join(
            f'<request id="{int(r["request_id"])}">\ntitle: {_data(r["title"])}\n{_data(r["text"])}\n</request>'
            for r in need.get("requests", [])
        )
        first = prompt.render({"need": self._need_block(need), "requests": requests or "none"})
        messages = [{"role": "user", "content": first}, *(_scrub_turn(m) for m in transcript)]
        max_tokens, extended = cfg.max_tokens, False
        while True:
            started = time.perf_counter()
            try:
                turn = client.converse(
                    step=step, model=cfg.model, system=prompt.system, messages=messages, tools=tools,
                    schema=RelatedNeeds, max_tokens=max_tokens, allow_tools=allow_tools, inputs=_scrub({"need": need}),
                )  # fmt: skip
                if turn.output is not None:  # validated in our code, always
                    turn = Turn(turn.tool_calls, RelatedNeeds.model_validate(turn.output.model_dump()), turn.content,
                                turn.usage, turn.model, turn.stop_reason)  # fmt: skip
            except MaxTokens as exc:  # one retry with a higher limit, as for every step
                self._run(
                    step, prompt, cfg.model, "max_tokens", started, None, exc.usage, "max_tokens", need_id
                )
                if extended:
                    raise TerminalError(f"{step}: hit max_tokens twice") from exc
                extended, max_tokens = True, max_tokens * 2
                continue
            except (BadOutput, Refused) as exc:  # no repair loop inside an agent turn: the run ends
                outcome = "validation_error" if isinstance(exc, BadOutput) else "refusal"
                self._run(step, prompt, cfg.model, outcome, started, None, exc.usage, str(exc), need_id)
                raise TerminalError(f"{step}: {exc}") from exc
            except (TransientError, TerminalError) as exc:
                self._run(
                    step, prompt, cfg.model, "provider_error", started, None, error=str(exc), need_id=need_id
                )
                raise
            except Exception as exc:
                self._run(step, prompt, cfg.model, "error", started, None, error=f"{type(exc).__name__}: {exc}",
                          need_id=need_id)  # fmt: skip
                raise
            break
        run_id = self._run(step, prompt, turn.model, "ok", started, None, turn.usage, need_id=need_id)
        return turn, run_id

    def decision_brief(
        self,
        *,
        need: dict[str, Any],
        facts: dict[str, dict[str, Any]],
        requests: list[dict[str, Any]],
        related: list[dict[str, Any]],
        goals: Sequence[Goal],
        repair: str | None = None,
        related_status: str = "complete",
        need_id: int | None = None,
    ) -> tuple[DecisionBrief, int]:
        """One call for the brief. Figures go in as keyed facts; code checks every claim afterwards, and a
        repair round names the claims that failed (app/ai/brief.py decides what failed)."""
        fact_lines = "\n".join(
            f'<fact key="{html.escape(k)}" label="{_attr(str(f["label"]))}">{_data(str(f["display"]))}</fact>'
            for k, f in facts.items()
        )
        request_blocks = "\n".join(
            f'<request id="{int(r["request_id"])}" requester_role="{_attr(r.get("role") or "unknown")}" '
            f'account="{_attr(r.get("account") or "none")}" segment="{html.escape(r.get("segment") or "none")}">'
            f"\n{_data(r['text'])}\n</request>"
            for r in requests
        )
        if related_status.startswith("unavailable"):
            related_block = (
                "<not_checked>Related needs are not available: the overlap search didn't finish "
                f"({_data(related_status)}). Leave related_needs empty.</not_checked>"
            )
        else:
            related_block = (
                "\n".join(
                    f'<related id="{int(x["need_id"])}" relation="{html.escape(x["relation"])}">\n'
                    f"title: {_data(x['need_title'] or '')}\nwhy: {_data(x['rationale'])}\n"
                    f"quote: {_data(x['quote'])}\n</related>"
                    for x in related
                )
                or "none found"
            )
            if related_status.startswith("incomplete"):
                related_block += f"\n<note>{_data(related_status)}</note>"
        goal_blocks = "\n".join(
            f'<goal key="{html.escape(g.key)}">{html.escape(g.title)}: {html.escape(g.description)}</goal>'
            for g in goals
        )
        verification = (
            f"<verification>Your previous brief had claims that failed the checks below. Fix each one: quote "
            f"requests exactly, cite only fact keys from <facts>, type no figures that aren't facts, and list "
            f"only needs from <related_needs>.\n{_data(repair)}</verification>"
            if repair
            else ""
        )
        values = {
            "need": self._need_block(need), "facts": fact_lines or "none", "requests": request_blocks or "none",
            "related": related_block, "goals": goal_blocks, "verification": verification,
        }  # fmt: skip
        inputs = {"need": need, "facts": facts, "requests": requests, "related": related,
                  "related_status": related_status, "goals": [{"key": g.key, "title": g.title} for g in goals]}  # fmt: skip
        out, run_id = self._call("decision_brief", DecisionBrief, values, inputs, None, need_id)
        assert isinstance(out, DecisionBrief)
        return out, run_id

    @staticmethod
    def _need_block(need: dict[str, Any]) -> str:
        return "\n".join(
            f"{k}: {_data(str(need.get(k) or 'unknown'))}"
            for k in ("title", "problem", "persona", "job_to_be_done", "product_area", "status")
            if k in need
        )

    def _prompt(self, step: str) -> Prompt:
        name = PROMPT_FOR_STEP[step]
        if name not in self._prompts:
            self._prompts[name] = Prompt.load(name, self.prompt_dir)
        return self._prompts[name]

    def _price(self, step: str, served: str) -> dict[str, float]:
        """The served model's price, else the configured one's: the API may answer with a dated id
        (claude-haiku-4-5-20251001 for claude-haiku-4-5). An unpriced model is an error, never a free call."""
        price = self.prices.get(served) or self.prices.get(self.steps[step].model)
        if price is None:
            raise KeyError(f"no price for model {self.steps[step].model!r} in config/prices.yaml")
        return price

    def _cost(self, step: str, served: str, usage: Usage) -> float:
        price = self._price(step, served)
        cached = usage.cache_creation_input_tokens * 1.25 + usage.cache_read_input_tokens * 0.1
        return (
            (usage.input_tokens + cached) * price["input"] + usage.output_tokens * price["output"]
        ) / 1_000_000

    def _run(self, step: str, prompt: Prompt, model: str, outcome: str, started: float, request_id: int | None,
             usage: Usage | None = None, error: str | None = None, need_id: int | None = None) -> int:  # fmt: skip
        usage = usage or Usage(0, 0)
        return self.record(
            AIRun(
                step=step,
                model=model,
                prompt_version=prompt.version,
                input_tokens=usage.input_tokens,
                output_tokens=usage.output_tokens,
                cache_read_tokens=usage.cache_read_input_tokens,
                cache_write_tokens=usage.cache_creation_input_tokens,
                cost_usd=self._cost(step, model, usage),
                latency_ms=int((time.perf_counter() - started) * 1000),
                outcome=outcome,
                error=error[:500] if error else None,
                request_id=request_id,
                need_id=need_id,
                trace_id=current_request_id.get(),
            )
        )

    def _call(
        self,
        step: str,
        schema: type[BaseModel],
        values: dict[str, str],
        inputs: dict[str, Any],
        request_id: int | None,
        need_id: int | None = None,
        check: Check | None = None,
        max_tokens: int | None = None,
    ) -> tuple[BaseModel, int]:
        """One logical call: at most one repair retry for bad output, one retry with a higher limit on max_tokens."""
        prompt, cfg = self._prompt(step), self.steps[step]
        self._price(step, cfg.model)  # fail before paying for a call we couldn't cost
        user, inputs = prompt.render(values), _scrub(inputs)
        max_tokens = max_tokens or cfg.max_tokens
        repaired = extended = False
        while True:
            started = time.perf_counter()
            try:
                reply = self.client.complete(
                    step=step, model=cfg.model, system=prompt.system, user=user, schema=schema,
                    max_tokens=max_tokens, effort=cfg.effort, inputs=inputs, cache=cfg.cache,
                )  # fmt: skip
                output = schema.model_validate(reply.output.model_dump())  # validated in our code, always
                problem = check(output) if check else None
                if problem:
                    raise BadOutput(problem, reply.usage)
            except BadOutput as exc:
                self._run(
                    step,
                    prompt,
                    cfg.model,
                    "validation_error",
                    started,
                    request_id,
                    exc.usage,
                    str(exc),
                    need_id,
                )
                if repaired:
                    raise TerminalError(f"{step}: output failed validation twice: {exc}") from exc
                repaired = True
                user = (
                    f"{user}\n\n<repair>Your previous answer did not match the schema: {html.escape(str(exc)[:300])}. "
                    "Answer again, matching the schema exactly.</repair>"
                )
                continue
            except MaxTokens as exc:
                self._run(
                    step,
                    prompt,
                    cfg.model,
                    "max_tokens",
                    started,
                    request_id,
                    exc.usage,
                    "max_tokens",
                    need_id,
                )
                if extended:
                    raise TerminalError(f"{step}: hit max_tokens twice") from exc
                extended, max_tokens = True, max_tokens * 2
                continue
            except Refused as exc:
                self._run(
                    step, prompt, cfg.model, "refusal", started, request_id, exc.usage, str(exc), need_id
                )
                raise TerminalError(f"{step}: {exc}") from exc
            except TransientError as exc:
                self._run(
                    step,
                    prompt,
                    cfg.model,
                    "provider_error",
                    started,
                    request_id,
                    error=str(exc),
                    need_id=need_id,
                )
                raise
            except TerminalError as exc:
                self._run(
                    step,
                    prompt,
                    cfg.model,
                    "provider_error",
                    started,
                    request_id,
                    error=str(exc),
                    need_id=need_id,
                )
                raise
            except Exception as exc:  # anything unmapped is still recorded (rule 5), then propagates
                self._run(
                    step,
                    prompt,
                    cfg.model,
                    "error",
                    started,
                    request_id,
                    error=f"{type(exc).__name__}: {exc}",
                    need_id=need_id,
                )
                raise
            run_id = self._run(
                step, prompt, reply.model, "ok", started, request_id, usage=reply.usage, need_id=need_id
            )
            return output, run_id


def _last_tool_result(messages: list[dict[str, Any]]) -> dict[str, Any] | None:
    """The newest tool result in a transcript, parsed (offline baseline only; results are escaped JSON)."""
    for m in reversed(messages):
        if m["role"] == "user" and isinstance(m["content"], list):
            for b in m["content"]:
                if b.get("type") == "tool_result" and not b.get("is_error"):
                    try:
                        parsed = json.loads(html.unescape(str(b["content"])))
                    except ValueError:
                        return None
                    return parsed if isinstance(parsed, dict) else None
    return None


def _body(text: str) -> str:
    """A request's text without its title line, when it has more than one line."""
    lines = [x for x in text.split("\n") if x.strip()]
    return "\n".join(lines[1:]) if len(lines) > 1 else text


def _first_sentence(text: str, limit: int = 120) -> str:
    first = re.split(r"(?<=[.!?])\s", text.strip(), maxsplit=1)[0]
    if len(first) <= limit:
        return first.strip()
    return first[:limit].rsplit(" ", 1)[0].strip()  # whole words, still a verbatim passage


class AnthropicClient:
    """Live calls through the Anthropic SDK.

    Uses messages.create with output_config.format (a JSON schema from the Pydantic model), not
    messages.parse: parse validates inside the SDK before returning, so a refusal or a max_tokens stop
    would surface as a validation error and lose its usage. Here stop_reason is checked first and the
    JSON is validated in our code, with the usage attached to every outcome so failed calls are costed.
    """

    name = "anthropic"

    def __init__(
        self,
        timeout_seconds: float = 30.0,
        max_retries: int = 2,
        http_client: Any = None,
        api_key: str | None = None,
        step_timeouts: dict[str, float] | None = None,
    ) -> None:
        import anthropic

        self._sdk = anthropic
        self._timeouts = step_timeouts or {}  # a long output (the brief) needs more than the default timeout
        kwargs: dict[str, Any] = {"timeout": timeout_seconds, "max_retries": max_retries}
        if http_client is not None:
            kwargs["http_client"] = http_client
        if api_key is not None:
            kwargs["api_key"] = api_key
        self._client = anthropic.Anthropic(**kwargs)

    def complete(
        self,
        *,
        step: str,
        model: str,
        system: str,
        user: str,
        schema: type[BaseModel],
        max_tokens: int,
        effort: str | None,
        inputs: dict[str, Any],
        cache: bool = False,
    ) -> Reply:
        output_config: dict[str, Any] = {"format": self._format(schema)}
        if effort:
            output_config["effort"] = effort
        system_param: Any = (
            [{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}] if cache else system
        )
        response, usage = self._create(
            step,
            model=model,
            max_tokens=max_tokens,
            system=system_param,
            messages=[{"role": "user", "content": user}],
            output_config=output_config,
        )
        text = next((b.text for b in response.content if b.type == "text"), "")
        return Reply(self._validate(schema, text, usage), usage, response.model)

    def converse(
        self,
        *,
        step: str,
        model: str,
        system: str,
        messages: list[dict[str, Any]],
        tools: list[ToolSpec],
        schema: type[BaseModel],
        max_tokens: int,
        allow_tools: bool,
        inputs: dict[str, Any],
    ) -> Turn:
        """One agent turn. Tools are strict (schema-valid arguments); tool_choice stays auto, because forcing a
        tool is rejected by current models. allow_tools=False sends tool_choice none: answer only."""
        kwargs: dict[str, Any] = {
            "model": model,
            "max_tokens": max_tokens,
            "system": system,
            "messages": messages,
            "tools": [
                {"name": t.name, "description": t.description, "input_schema": t.input_schema, "strict": True}
                for t in tools
            ],
            "output_config": {"format": self._format(schema)},
        }
        if not allow_tools:
            kwargs["tool_choice"] = {"type": "none"}
        response, usage = self._create(step, **kwargs)
        content = [b.model_dump(exclude_none=True) for b in response.content]  # sent back unchanged next turn
        calls = [ToolCall(b.id, b.name, dict(b.input)) for b in response.content if b.type == "tool_use"]
        if calls:
            return Turn(calls, None, content, usage, response.model, str(response.stop_reason))
        text = next((b.text for b in response.content if b.type == "text"), "")
        return Turn(
            [], self._validate(schema, text, usage), content, usage, response.model, str(response.stop_reason)
        )

    def _format(self, schema: type[BaseModel]) -> dict[str, Any]:
        return {"type": "json_schema", "schema": self._sdk.transform_schema(schema)}

    def _create(self, step: str, **kwargs: Any) -> tuple[Any, Usage]:
        """messages.create with provider errors mapped, stop_reason checked first, and usage always kept."""
        sdk = self._sdk
        client = (
            self._client.with_options(timeout=self._timeouts[step])
            if step in self._timeouts
            else self._client
        )
        try:
            create: Any = client.messages.create  # output_config is newer than the typed overloads
            response = create(**kwargs)
        except (sdk.APITimeoutError, sdk.APIConnectionError) as exc:
            raise TransientError(f"{type(exc).__name__}: {exc}"[:300]) from exc
        except sdk.APIStatusError as exc:
            if exc.status_code >= 500 or exc.status_code in (408, 409, 429):
                raise TransientError(f"{exc.status_code}: {exc.message}"[:300]) from exc
            raise TerminalError(f"{exc.status_code}: {exc.message}"[:300]) from exc
        u = response.usage
        usage = Usage(
            u.input_tokens,
            u.output_tokens,
            getattr(u, "cache_read_input_tokens", None) or 0,
            getattr(u, "cache_creation_input_tokens", None) or 0,
        )
        if response.stop_reason == "refusal":
            details = getattr(response, "stop_details", None)
            raise Refused(getattr(details, "category", None), usage)
        if response.stop_reason == "max_tokens":
            raise MaxTokens(usage)
        return response, usage

    @staticmethod
    def _validate(schema: type[BaseModel], text: str, usage: Usage) -> BaseModel:
        try:
            return schema.model_validate_json(text)
        except ValidationError as exc:
            # locations and messages only: the model's own output (which could echo injected text) isn't
            # sent back in the repair turn
            problems = "; ".join(
                f"{'.'.join(map(str, e['loc']))}: {e['msg']}"
                for e in exc.errors(include_input=False, include_url=False)
            )
            raise BadOutput(problems[:500], usage) from exc


class OfflineClient:
    """AI_MODE=offline: no provider. Extraction by keyword heuristics; there is no adjudicator, because the
    pipeline routes on similarity alone in this mode (the baseline, evals/REPORT.md §1)."""

    name = "offline-baseline"
    similarity_floor = 0.5  # below this the nearest need is not reported as related
    PERSONAS: ClassVar[list[tuple[tuple[str, ...], str]]] = [
        (("it ", "systems", "identity", "infrastructure", "security engineer", "network"), "it_admin"),
        (("security", "compliance", "privacy", "ciso", "audit", "data protection"), "security_compliance"),
        (("finance", "controller", "accountant", "fp&a", "cfo"), "finance"),
        (("data engineer", "analytics engineer", "platform"), "data_engineer"),
        (("analyst", "bi "), "analyst"),
        (("product",), "product_manager"),
        (("owner", "founder"), "smb_owner"),
        (("operations", "ops", "warehouse", "logistics", "store"), "ops_manager"),
    ]
    AREAS: ClassVar[list[tuple[tuple[str, ...], ProductArea]]] = [
        (
            ("sso", "saml", "okta", "azure ad", "login", "sign in", "scim", "permission", "audit", "role"),
            "security_admin",
        ),
        (("slack", "email", "pdf", "schedule", "share", "digest"), "sharing"),
        (("export", "excel", "xlsx", "backup", "download"), "export"),
        (("import", "upload", "csv", "snowflake", "connector", "spreadsheet"), "data_sources"),
        (("alert", "notify", "threshold"), "alerts"),
        (("mobile", "phone", "ipad", "tablet"), "mobile"),
        (("slow", "load", "performance", "timeout"), "performance"),
        (("template", "starter", "onboard"), "onboarding"),
        (("comment", "annotat"), "collaboration"),
        (("spanish", "portuguese", "español", "language"), "localization"),
        (("dark",), "ui"),
        (("embed", "portal", "white-label"), "embedded"),
    ]

    @staticmethod
    def _brief(inputs: dict[str, Any]) -> DecisionBrief:
        """Offline brief: the gathered facts and verbatim quotes in a fixed template. No synthesis, and it says so."""
        need, facts, requests = inputs["need"], inputs["facts"], inputs["requests"]
        roles = sorted({str(r["role"]) for r in requests if r.get("role")})
        segments = sorted({str(r["segment"]).replace("_", " ") for r in requests if r.get("segment")})

        def keys(*wanted: str) -> list[str]:
            return [k for k in wanted if k in facts]

        impact = [
            ImpactClaim(statement="Revenue of the accounts asking.", fact_keys=keys("arr_customers", "pipeline_prospects")),
            ImpactClaim(statement="Urgency: the highest severity asked and renewals soon.",
                        fact_keys=keys("max_severity", "renewals_90d")),
            ImpactClaim(statement="The priority score and its parts.",
                        fact_keys=keys("priority", "demand", "urgency", "strategic_fit")),
        ]  # fmt: skip
        evidence = [
            EvidenceQuote(request_id=int(r["request_id"]), quote=_first_sentence(_body(str(r["text"]))))
            for r in requests[:3]
        ]
        related = [
            BriefRelatedNeed(need_id=int(x["need_id"]), relation=x["relation"],
                             why_it_matters="Found by the offline baseline (embedding similarity); a PM should confirm.")
            for x in inputs.get("related", [])
        ]  # fmt: skip
        questions = ["What would it take to build, and which team owns it?"]
        if str(inputs.get("related_status", "")).startswith("unavailable"):
            questions.append("Related needs were not checked: the overlap search didn't finish.")
        return DecisionBrief(
            summary=f"{len(requests)} requests ask for this: {need['title']}.",
            problem=str(need.get("problem") or need["title"]),
            who_is_affected=f"Requesters: {', '.join(roles) or 'unknown'}. Segments: {', '.join(segments) or 'unknown'}.",
            business_impact=[c for c in impact if c.fact_keys], evidence=evidence, related_needs=related,
            options=[
                BriefOption(name="Plan it", description="Schedule the work for this need.",
                            tradeoffs="Serves the accounts asking now; costs engineering time not yet estimated."),
                BriefOption(name="Wait for more evidence", description="Keep collecting requests and support.",
                            tradeoffs="Costs nothing now; the accounts asking keep waiting."),
            ],
            recommendation="Offline template: no model wrote this brief, so it makes no recommendation. "
            "Decide from the facts and the quotes.",
            confidence=0.0,
            confidence_rationale="Offline template (AI_MODE=offline): facts and quotes only, no model judgment.",
            risks=["Generated without a model: the evidence is listed, not weighed."],
            open_questions=questions,
        )  # fmt: skip

    @staticmethod
    def _drafts(inputs: dict[str, Any]) -> UpdateDrafts:
        """Offline drafts: a fixed template filled with the PM's reason and each supporter's own request."""
        title = str(inputs["need"]["title"])
        status = str(inputs["status"]).replace("_", " ")
        reason = str(inputs["reason"]).strip().rstrip(".") + "."
        when = f" We're aiming for {inputs['target_date']}." if inputs.get("target_date") else ""
        people = [
            RequesterUpdate(
                requester_id=x["requester_id"],
                body=f"Hi {str(x['name']).split()[0]}, thanks for asking about \u201c{x['asked']}\u201d. "
                f"We've marked \u201c{title}\u201d as {status}. {reason}{when}",
            )
            for x in inputs["supporters"]
        ]
        notes = [
            CsNote(
                account_id=a["account_id"],
                body=f"{a['name']}: \u201c{title}\u201d is now {status}. Reason: {reason} "
                f"Asked for by {', '.join(a['supporters'])}.",
            )
            for a in inputs["accounts"]
        ]
        return UpdateDrafts(requester_updates=people, cs_notes=notes)

    def complete(
        self,
        *,
        step: str,
        model: str,
        system: str,
        user: str,
        schema: type[BaseModel],
        max_tokens: int,
        effort: str | None,
        inputs: dict[str, Any],
        cache: bool = False,
    ) -> Reply:
        if step == "stakeholder_update":
            return Reply(self._drafts(inputs), Usage(0, 0), "offline-baseline")
        if step == "decision_brief":
            return Reply(self._brief(inputs), Usage(0, 0), "offline-baseline")
        if step != "extract":
            raise TerminalError("offline mode has no adjudicator; the pipeline routes on similarity")
        text = str(inputs.get("text") or "")
        role = f" {str(inputs.get('role') or '').lower()} "
        title = text.split("\n")[0].strip()[:150] or "A request"
        lowered = text.lower()
        persona = next((p for keys, p in self.PERSONAS if any(k in role for k in keys)), "end_user")
        area = next((a for keys, a in self.AREAS if any(k in lowered for k in keys)), "other")
        out = Extraction(
            need_statement=title, problem=title, persona=persona, job_to_be_done=title, proposed_solution="none stated",
            product_area=area, severity_signal="unknown", evidence=[], confidence=0.2,
            rationale="Offline heuristics (AI_MODE=offline): title, role keywords and text keywords only.",
        )  # fmt: skip
        return Reply(out, Usage(0, 0), "offline-baseline")

    def converse(
        self,
        *,
        step: str,
        model: str,
        system: str,
        messages: list[dict[str, Any]],
        tools: list[ToolSpec],
        schema: type[BaseModel],
        max_tokens: int,
        allow_tools: bool,
        inputs: dict[str, Any],
    ) -> Turn:
        """The offline baseline for the overlap agent: search once with the need's text, read the nearest need
        above the similarity floor, report it as an overlap. Deterministic, and labelled as the baseline."""
        if step != "related_needs":
            raise TerminalError(f"offline mode has no tool loop for {step}")
        last = _last_tool_result(messages)
        need = inputs["need"]
        none = Usage(0, 0)
        if last is None and allow_tools:
            call = ToolCall(
                "offline-1", "search_needs", {"query": f"{need['title']}. {need['problem']}"[:300]}
            )
            return Turn([call], None, [{"type": "tool_use", "id": call.id, "name": call.name, "input": call.input}],
                        none, self.name, "tool_use")  # fmt: skip
        if last and "needs" in last and allow_tools:
            near = [n for n in last["needs"] if n["similarity"] >= self.similarity_floor]
            if near:
                call = ToolCall("offline-2", "get_need", {"need_id": int(near[0]["need_id"])})
                return Turn([call], None, [{"type": "tool_use", "id": call.id, "name": call.name, "input": call.input}],
                            none, self.name, "tool_use")  # fmt: skip
        found = []
        if last and last.get("requests"):
            first = last["requests"][0]
            found.append(RelatedFinding(
                need_id=int(last["need_id"]), relation="overlaps", request_id=int(first["request_id"]),
                rationale="Offline baseline: the nearest need by embedding similarity; no model judged the relation.",
                quote=_first_sentence(str(first["text"])),
            ))  # fmt: skip
        out = RelatedNeeds(related=found)
        return Turn([], out, [{"type": "text", "text": out.model_dump_json()}], none, self.name, "end_turn")


class FaultInjectingClient:
    """Test only (APP_ENV=test, wired in factory.make_client): text containing MARKER fails like a provider
    refusal, so the end-to-end specs can drive the failure path (needs_review) without a network."""

    MARKER = "[simulate-provider-failure]"

    def __init__(self, inner: LLMClient) -> None:
        self.inner, self.name = inner, f"faulty-{inner.name}"

    def complete(self, **kw: Any) -> Reply:
        if self.MARKER in str(kw.get("inputs", {}).get("text", "")):
            raise TerminalError("simulated provider failure (test environment)")
        return self.inner.complete(**kw)

    def converse(self, **kw: Any) -> Turn:
        if not isinstance(self.inner, ToolClient):
            raise TerminalError(f"the {self.inner.name} client can't run tools")
        return self.inner.converse(**kw)


def recorder(engine: Any) -> Recorder:
    """Write each AIRun in its own transaction, so failed calls are recorded even when the pipeline rolls back."""
    from sqlmodel import Session

    def record(run: AIRun) -> int:
        with Session(engine) as session:
            session.add(run)
            session.commit()
            session.refresh(run)
            assert run.id is not None
            return run.id

    return record
