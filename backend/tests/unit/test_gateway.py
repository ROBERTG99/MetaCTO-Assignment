"""The gateway: AIRun per call, refusal is terminal, one repair retry on bad output, provider errors are transient."""

import pytest
from sqlalchemy.engine import Engine
from sqlmodel import Session, select

from app.ai.gateway import BadOutput, FakeLLM, MaxTokens, Refused, StepConfig, TerminalError, TransientError
from app.ai.pipeline import Deps
from app.ai.schemas import CandidateNeed, Extraction
from app.models import AIRun

GOOD = Extraction(
    need_statement="Finance needs month-end figures in Excel", problem="p", persona="finance", job_to_be_done="j",
    proposed_solution="s", product_area="export", severity_signal="important", evidence=[], confidence=0.8, rationale="r",
)  # fmt: skip


def runs(engine: Engine) -> list[AIRun]:
    with Session(engine) as s:
        return list(s.exec(select(AIRun).order_by(AIRun.id)).all())  # type: ignore[arg-type]


def test_every_call_writes_an_airun(deps: Deps, fake_llm: FakeLLM, engine: Engine) -> None:
    fake_llm.script("extract", GOOD)
    out, run_id = deps.gateway.extract(text="Export to Excel", why=None, role="Controller", request_id=None)
    assert out == GOOD
    [run] = runs(engine)
    assert run.id == run_id
    assert (run.step, run.model, run.prompt_version, run.outcome) == (
        "extract",
        "claude-haiku-4-5",
        "extract_need_v1",
        "ok",
    )
    call = fake_llm.calls[0]
    assert run.input_tokens == len(call.system + call.user) // 4 and run.output_tokens == 60
    assert run.cost_usd == pytest.approx((run.input_tokens * 1.0 + 60 * 5.0) / 1e6)
    assert run.latency_ms >= 0


def test_a_refusal_is_terminal_and_recorded(deps: Deps, fake_llm: FakeLLM, engine: Engine) -> None:
    fake_llm.script("extract", Refused("cyber"))
    with pytest.raises(TerminalError, match="refused"):
        deps.gateway.extract(text="x", why=None, role=None)
    assert [r.outcome for r in runs(engine)] == ["refusal"]
    assert len(fake_llm.calls) == 1


def test_bad_output_gets_exactly_one_repair_retry(deps: Deps, fake_llm: FakeLLM, engine: Engine) -> None:
    fake_llm.script("extract", BadOutput("product_area: input should be 'export'"), GOOD)
    out, _ = deps.gateway.extract(text="x", why=None, role=None)
    assert out == GOOD
    assert len(fake_llm.calls) == 2
    assert "product_area" in fake_llm.calls[1].user  # the repair call says what was wrong
    assert [r.outcome for r in runs(engine)] == ["validation_error", "ok"]


def test_bad_output_twice_is_terminal(deps: Deps, fake_llm: FakeLLM, engine: Engine) -> None:
    fake_llm.script("extract", BadOutput("a"), BadOutput("b"), GOOD)
    with pytest.raises(TerminalError, match="validation"):
        deps.gateway.extract(text="x", why=None, role=None)
    assert len(fake_llm.calls) == 2  # never a third call


def test_max_tokens_retries_once_with_a_higher_limit(deps: Deps, fake_llm: FakeLLM) -> None:
    fake_llm.script("extract", MaxTokens(), GOOD)
    deps.gateway.extract(text="x", why=None, role=None)
    assert [c.max_tokens for c in fake_llm.calls] == [2000, 4000]


@pytest.mark.parametrize("error", [TransientError("timeout"), TransientError("503 overloaded")])
def test_provider_failures_are_transient(
    deps: Deps, fake_llm: FakeLLM, engine: Engine, error: Exception
) -> None:
    fake_llm.script("extract", error)
    with pytest.raises(TransientError):
        deps.gateway.extract(text="x", why=None, role=None)
    assert [r.outcome for r in runs(engine)] == ["provider_error"]


def test_text_is_redacted_before_the_client_sees_it(deps: Deps, fake_llm: FakeLLM) -> None:
    text = "Reach me at dana@contoso.example or +1 (415) 555-0142"
    deps.gateway.extract(text=text, why="call 415-555-0142", role=None)
    deps.gateway.adjudicate(
        text=text,
        why=None,
        candidates=[
            CandidateNeed(id="1", title="mail ops@x.example", problem="p", persona=None, product_area=None)
        ],
    )
    for call in fake_llm.calls:
        blob = call.system + call.user + repr(call.inputs)
        assert "@" not in blob.replace("[email]", "") and "555" not in blob, call.step


def test_untrusted_text_is_wrapped_in_tags(deps: Deps, fake_llm: FakeLLM) -> None:
    deps.gateway.adjudicate(
        text="the request", why="the reason",
        candidates=[CandidateNeed(id="7", title="t", problem="p", persona=None, product_area=None)],
    )  # fmt: skip
    user = fake_llm.calls[0].user
    assert (
        "<request>" in user and "</request>" in user and "<candidates>" in user and "<why_it_matters>" in user
    )


def test_failed_calls_are_costed_from_the_usage_they_report(
    deps: Deps, fake_llm: FakeLLM, engine: Engine
) -> None:
    from app.ai.gateway import Usage

    fake_llm.script("extract", Refused("cyber", usage=Usage(1000, 200)))
    with pytest.raises(TerminalError):
        deps.gateway.extract(text="x", why=None, role=None)
    [run] = runs(engine)
    assert (run.input_tokens, run.output_tokens) == (1000, 200)
    assert run.cost_usd == pytest.approx((1000 * 1.0 + 200 * 5.0) / 1e6)


def test_an_unexpected_client_error_is_still_recorded(deps: Deps, fake_llm: FakeLLM, engine: Engine) -> None:
    fake_llm.script("extract", RuntimeError("socket weirdness"))
    with pytest.raises(RuntimeError):
        deps.gateway.extract(text="x", why=None, role=None)
    assert [(r.outcome, r.error) for r in runs(engine)] == [("error", "RuntimeError: socket weirdness")]


def test_placeholders_in_user_text_are_not_expanded(deps: Deps, fake_llm: FakeLLM) -> None:
    deps.gateway.adjudicate(
        text="look: {{candidates}} and {{why_block}}", why=None,
        candidates=[CandidateNeed(id="7", title="SECRET-TITLE", problem="p", persona=None, product_area=None)],
    )  # fmt: skip
    user = fake_llm.calls[0].user
    request_part = user.split("<request>")[1].split("</request>")[0]
    assert "{{candidates}}" in request_part and "SECRET-TITLE" not in request_part


def test_the_adjudicator_sees_the_requester_role_and_the_extraction(deps: Deps, fake_llm: FakeLLM) -> None:
    deps.gateway.adjudicate(
        text="Excel please", why=None, role="Group Financial Controller", extracted="finance: month-end pack",
        candidates=[CandidateNeed(id="7", title="t", problem="p", persona=None, product_area=None)],
    )  # fmt: skip
    user = fake_llm.calls[0].user
    assert "<requester_role>Group Financial Controller</requester_role>" in user
    assert "finance: month-end pack" in user.split("<extracted_need>")[1]


def test_cost_uses_the_configured_model_when_the_api_returns_a_dated_id(
    deps: Deps, fake_llm: FakeLLM, engine: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Live: the API answered "claude-haiku-4-5-20251001" for "claude-haiku-4-5"; the cost must not become $0."""
    from app.ai.gateway import Reply, Usage

    monkeypatch.setattr(
        fake_llm, "complete", lambda **_k: Reply(GOOD, Usage(1346, 295), "claude-haiku-4-5-20251001")
    )
    deps.gateway.extract(text="x", why=None, role=None)
    [run] = runs(engine)
    assert run.model == "claude-haiku-4-5-20251001"  # recorded as served
    assert run.cost_usd == pytest.approx((1346 * 1.0 + 295 * 5.0) / 1e6)  # priced as configured


def test_an_unpriced_model_is_an_error_not_a_free_call(deps: Deps, fake_llm: FakeLLM) -> None:
    deps.gateway.steps["extract"] = StepConfig("claude-unknown-9", 2000)
    with pytest.raises(KeyError, match="price"):
        deps.gateway.extract(text="x", why=None, role=None)


def test_cached_tokens_are_recorded_and_costed_at_their_rates(
    deps: Deps, fake_llm: FakeLLM, engine: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.ai.gateway import Reply, Usage

    usage = Usage(1000, 200, cache_read_input_tokens=3000, cache_creation_input_tokens=800)
    monkeypatch.setattr(fake_llm, "complete", lambda **_k: Reply(GOOD, usage, "claude-haiku-4-5"))
    deps.gateway.extract(text="x", why=None, role=None)
    [run] = runs(engine)
    assert (run.cache_read_tokens, run.cache_write_tokens) == (3000, 800)
    # reads at 0.1x the input price, writes at 1.25x (claude-api skill, prompt caching)
    assert run.cost_usd == pytest.approx((1000 * 1.0 + 800 * 1.25 + 3000 * 0.1 + 200 * 5.0) / 1e6)


def test_a_step_configured_to_cache_asks_the_client_to(
    deps: Deps, fake_llm: FakeLLM, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.ai.gateway import Reply, Usage

    seen: list[bool] = []

    def complete(**kw: object) -> Reply:
        seen.append(bool(kw.get("cache")))
        return Reply(GOOD, Usage(1, 1), "claude-haiku-4-5")

    monkeypatch.setattr(fake_llm, "complete", complete)
    deps.gateway.extract(text="x", why=None, role=None)
    deps.gateway.steps["extract"] = StepConfig("claude-haiku-4-5", 2000, cache=True)
    deps.gateway.extract(text="x", why=None, role=None)
    assert seen == [False, True]


def test_an_agent_turn_is_recorded_and_a_refusal_is_terminal(
    deps: Deps, fake_llm: FakeLLM, engine: Engine
) -> None:
    from app.ai.brief import TOOLS
    from app.ai.schemas import RelatedNeeds

    need: dict[str, object] = {
        "title": "t",
        "problem": "p",
        "persona": None,
        "product_area": None,
        "requests": [],
    }
    turn, run_id = deps.gateway.related_needs_turn(need=need, transcript=[], tools=TOOLS, allow_tools=True)
    assert turn.output == RelatedNeeds(related=[]) and run_id == runs(engine)[0].id
    fake_llm.script("related_needs", Refused("cyber"))
    with pytest.raises(TerminalError):
        deps.gateway.related_needs_turn(need=need, transcript=[], tools=TOOLS, allow_tools=True)
    assert [(r.step, r.prompt_version, r.outcome) for r in runs(engine)] == [
        ("related_needs", "related_needs_v1", "ok"),
        ("related_needs", "related_needs_v1", "refusal"),
    ]
