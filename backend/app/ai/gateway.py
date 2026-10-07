"""The only module that talks to a model provider (CLAUDE.md rule 5).

Callers ask for a step (extract, adjudicate). The gateway renders the versioned prompt, redacts the text,
calls the configured client, validates the output with Pydantic, handles refusals, max_tokens and
validation repair, maps provider failures to TransientError or TerminalError, and writes one AIRun per call.
"""

import html
import re
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, ClassVar, Protocol, TypeVar

from pydantic import BaseModel, ValidationError

from app.ai.redact import redact
from app.ai.schemas import Adjudication, CandidateNeed, Extraction, ProductArea
from app.models import AIRun

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
    input_tokens: int
    output_tokens: int


@dataclass(frozen=True)
class Reply:
    output: BaseModel
    usage: Usage
    model: str


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
    ) -> Reply: ...


@dataclass
class FakeCall:
    step: str
    model: str
    system: str
    user: str
    inputs: dict[str, Any]
    max_tokens: int


Outcome = BaseModel | Exception
Responder = Callable[[dict[str, Any]], Outcome]


class FakeLLM:
    """Test double (CLAUDE.md rule 8). Scripted outcomes per step, in order; then a responder; then a default.

    Records exactly what it received, so tests can assert on redaction and prompts.
    """

    name = "fake"

    def __init__(self) -> None:
        self.calls: list[FakeCall] = []
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
    ) -> Reply:
        self.calls.append(FakeCall(step, model, system, user, inputs, max_tokens))
        if self._scripts.get(step):
            outcome = self._scripts[step].pop(0)
        elif step in self._responders:
            outcome = self._responders[step](inputs)
        else:
            outcome = self._default(step, inputs)
        if isinstance(outcome, Exception):
            raise outcome
        return Reply(outcome, Usage(input_tokens=len(system + user) // 4, output_tokens=60), model)

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
        raise ValueError(f"no default for step {step}")


@dataclass(frozen=True)
class StepConfig:
    model: str
    max_tokens: int
    effort: str | None = None


Recorder = Callable[[AIRun], int]
PROMPTS = Path(__file__).resolve().parent / "prompts"
PROMPT_FOR_STEP = {"extract": "extract_need_v1", "adjudicate": "adjudicate_v1"}
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


def _scrub(value: Any) -> Any:
    if isinstance(value, str):
        return redact(value)
    if isinstance(value, list):
        return [_scrub(v) for v in value]
    if isinstance(value, dict):
        return {k: _scrub(v) for k, v in value.items()}
    return value


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
        return (usage.input_tokens * price["input"] + usage.output_tokens * price["output"]) / 1_000_000

    def _run(self, step: str, prompt: Prompt, model: str, outcome: str, started: float, request_id: int | None,
             usage: Usage | None = None, error: str | None = None) -> int:  # fmt: skip
        usage = usage or Usage(0, 0)
        return self.record(
            AIRun(
                step=step,
                model=model,
                prompt_version=prompt.version,
                input_tokens=usage.input_tokens,
                output_tokens=usage.output_tokens,
                cost_usd=self._cost(step, model, usage),
                latency_ms=int((time.perf_counter() - started) * 1000),
                outcome=outcome,
                error=error[:500] if error else None,
                request_id=request_id,
            )
        )

    def _call(
        self,
        step: str,
        schema: type[BaseModel],
        values: dict[str, str],
        inputs: dict[str, Any],
        request_id: int | None,
    ) -> tuple[BaseModel, int]:
        """One logical call: at most one repair retry for bad output, one retry with a higher limit on max_tokens."""
        prompt, cfg = self._prompt(step), self.steps[step]
        self._price(step, cfg.model)  # fail before paying for a call we couldn't cost
        user, max_tokens, inputs = prompt.render(values), cfg.max_tokens, _scrub(inputs)
        repaired = extended = False
        while True:
            started = time.perf_counter()
            try:
                reply = self.client.complete(
                    step=step, model=cfg.model, system=prompt.system, user=user, schema=schema,
                    max_tokens=max_tokens, effort=cfg.effort, inputs=inputs,
                )  # fmt: skip
                output = schema.model_validate(reply.output.model_dump())  # validated in our code, always
            except BadOutput as exc:
                self._run(
                    step, prompt, cfg.model, "validation_error", started, request_id, exc.usage, str(exc)
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
                self._run(step, prompt, cfg.model, "max_tokens", started, request_id, exc.usage, "max_tokens")
                if extended:
                    raise TerminalError(f"{step}: hit max_tokens twice") from exc
                extended, max_tokens = True, max_tokens * 2
                continue
            except Refused as exc:
                self._run(step, prompt, cfg.model, "refusal", started, request_id, exc.usage, str(exc))
                raise TerminalError(f"{step}: {exc}") from exc
            except TransientError as exc:
                self._run(step, prompt, cfg.model, "provider_error", started, request_id, error=str(exc))
                raise
            except TerminalError as exc:
                self._run(step, prompt, cfg.model, "provider_error", started, request_id, error=str(exc))
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
                )
                raise
            run_id = self._run(step, prompt, reply.model, "ok", started, request_id, usage=reply.usage)
            return output, run_id


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
    ) -> None:
        import anthropic

        self._sdk = anthropic
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
    ) -> Reply:
        sdk = self._sdk
        output_config: dict[str, Any] = {
            "format": {"type": "json_schema", "schema": sdk.transform_schema(schema)}
        }
        if effort:
            output_config["effort"] = effort
        try:
            create: Any = self._client.messages.create  # output_config is newer than the typed overloads
            response = create(
                model=model,
                max_tokens=max_tokens,
                system=system,
                messages=[{"role": "user", "content": user}],
                output_config=output_config,
            )
        except (sdk.APITimeoutError, sdk.APIConnectionError) as exc:
            raise TransientError(f"{type(exc).__name__}: {exc}"[:300]) from exc
        except sdk.APIStatusError as exc:
            if exc.status_code >= 500 or exc.status_code in (408, 409, 429):
                raise TransientError(f"{exc.status_code}: {exc.message}"[:300]) from exc
            raise TerminalError(f"{exc.status_code}: {exc.message}"[:300]) from exc
        usage = Usage(response.usage.input_tokens, response.usage.output_tokens)
        if response.stop_reason == "refusal":
            details = getattr(response, "stop_details", None)
            raise Refused(getattr(details, "category", None), usage)
        if response.stop_reason == "max_tokens":
            raise MaxTokens(usage)
        text = next((b.text for b in response.content if b.type == "text"), "")
        try:
            output = schema.model_validate_json(text)
        except ValidationError as exc:
            raise BadOutput(str(exc)[:500], usage) from exc
        return Reply(output, usage, response.model)


class OfflineClient:
    """AI_MODE=offline: no provider. Extraction by keyword heuristics; there is no adjudicator, because the
    pipeline routes on similarity alone in this mode (the baseline, evals/REPORT.md §1)."""

    name = "offline-baseline"
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
    ) -> Reply:
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
