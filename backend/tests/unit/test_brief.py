"""Decision briefs (F6) with FakeLLM: the bounded overlap agent, verification in code, and the brief workflow.

FakeLLM is scripted to make tool calls, so every rule of the loop is exercised without a network: the cap,
read-only tools, cited and verbatim findings, money that comes only from the data, one repair round, a brief
that survives an agent failure, and a stored trajectory.
"""

import itertools
import json
from typing import Any

import pytest
from sqlmodel import Session, select

from app.ai.brief import CAP, TOOLS, build, run_agent
from app.ai.gateway import FakeLLM, TerminalError, ToolCall, TransientError
from app.ai.pipeline import Deps
from app.ai.schemas import (
    BriefRelatedNeed,
    DecisionBrief,
    EvidenceQuote,
    ImpactClaim,
    RelatedFinding,
    RelatedNeeds,
)
from app.models import AIRun, NeedStatus, RequestStatus, Segment
from tests.conftest import Factory

OKTA = "We are standardising every SaaS tool on Okta by Q1 and need SAML single sign-on."
AUDIT = "Security review blocks our rollout until SSO is enforced. Questions to ciso@northwind.example."
SCIM = "When someone leaves we remove them by hand in every tool; we need SCIM provisioning from Okta."


@pytest.fixture
def world(db: Session, make: Factory, deps: Deps) -> dict[str, Any]:
    north = make.account("Northwind", Segment.enterprise, arr=400_000)
    contoso = make.account("Contoso", Segment.mid_market, arr=120_000)
    fabrikam = make.account("Fabrikam", Segment.enterprise, arr=0, is_prospect=True, pipeline_value=250_000)
    priya = make.requester(north, "Priya", "Chief Information Officer")
    omar = make.requester(contoso, "Omar", "IT Manager")
    lena = make.requester(fabrikam, "Lena", "Head of IT")
    sso = make.need("IT admins need SSO before rollout", persona="it_admin", product_area="security_admin")
    scim = make.need(
        "IT admins need automatic user provisioning", persona="it_admin", product_area="security_admin"
    )
    dark = make.need("Users want a dark theme at night", persona="end_user", product_area="ui")
    okta = make.request(priya, sso, "Okta SSO", description=OKTA, status=RequestStatus.processed)
    audit = make.request(omar, sso, "Security review", description=AUDIT, status=RequestStatus.processed)
    make.request(
        lena,
        sso,
        "SAML for the pilot",
        description="Our pilot needs SAML login.",
        status=RequestStatus.processed,
    )
    scim_req = make.request(omar, scim, "SCIM", description=SCIM, status=RequestStatus.processed)
    make.request(
        lena,
        dark,
        "Dark mode",
        description="The white screen hurts at night.",
        status=RequestStatus.processed,
    )
    deps.search.rebuild(db)
    return {"sso": sso, "scim": scim, "dark": dark, "okta": okta, "audit": audit, "scim_req": scim_req}


def call(n: int, name: str, **args: Any) -> list[ToolCall]:
    return [ToolCall(f"t{n}", name, args)]


def found(w: dict[str, Any], quote: str = "we need SCIM provisioning from Okta", **kw: Any) -> RelatedFinding:
    base = dict(need_id=w["scim"].id, relation="depends_on", rationale="Provisioning follows sign-on.",
                request_id=w["scim_req"].id, quote=quote)  # fmt: skip
    return RelatedFinding(**{**base, **kw})


def brief(w: dict[str, Any], **kw: Any) -> DecisionBrief:
    base: dict[str, Any] = dict(
        summary="Enterprise IT asks for SSO before rollout.", problem="IT can't enforce one sign-in.",
        who_is_affected="IT admins at enterprise accounts.",
        business_impact=[ImpactClaim(statement="Customer revenue behind the need.", fact_keys=["arr_customers"])],
        evidence=[EvidenceQuote(request_id=w["okta"].id, quote="need SAML single sign-on")],
        related_needs=[], options=[], recommendation="Plan it.", confidence=0.7, confidence_rationale="Clear asks.",
        risks=[], open_questions=[],
    )  # fmt: skip
    return DecisionBrief(**{**base, **kw})


def runs(db: Session, step: str) -> list[AIRun]:
    return list(db.exec(select(AIRun).where(AIRun.step == step)).all())


# --- the agent is bounded ---------------------------------------------------------------------------------


def test_the_agent_stops_at_8_tool_calls_and_returns_what_it_found_flagged_incomplete(
    db: Session, deps: Deps, fake_llm: FakeLLM, world: dict[str, Any]
) -> None:
    for n in range(CAP):
        fake_llm.script("related_needs", call(n, "search_needs", query=f"single sign-on {n}"))
    fake_llm.script("related_needs", RelatedNeeds(related=[found(world)]))
    result = run_agent(db, world["sso"], deps)
    assert CAP == 8
    assert result.tool_calls == 8 and [s.status for s in result.steps] == ["ok"] * 8
    assert result.status == "incomplete" and "8" in (result.reason or "")
    assert fake_llm.turns[-1]["allow_tools"] is False  # the last turn may only answer
    assert [f.need_id for f in result.findings] == [world["scim"].id]  # what it found is kept


def test_calls_beyond_the_cap_in_one_turn_are_not_run(
    db: Session, deps: Deps, fake_llm: FakeLLM, world: dict[str, Any]
) -> None:
    for n in range(CAP - 1):
        fake_llm.script("related_needs", call(n, "get_trend", need_id=world["sso"].id))
    many = [ToolCall(f"x{i}", "get_need", {"need_id": world["scim"].id}) for i in range(3)]
    fake_llm.script("related_needs", many, RelatedNeeds(related=[]))
    result = run_agent(db, world["sso"], deps)
    assert result.tool_calls == 8
    assert [s.status for s in result.steps][-3:] == ["ok", "budget", "budget"]
    assert result.status == "incomplete"


def test_the_agent_only_gets_three_strict_read_only_tools(
    db: Session, deps: Deps, fake_llm: FakeLLM, world: dict[str, Any]
) -> None:
    run_agent(db, world["sso"], deps)
    sent = fake_llm.turns[0]["tools"]
    assert [t.name for t in sent] == ["search_needs", "get_need", "get_trend"] == [t.name for t in TOOLS]
    assert all(t.input_schema["additionalProperties"] is False for t in sent)
    assert fake_llm.turns[0]["allow_tools"] is True


def test_a_tool_call_outside_its_list_is_rejected_and_never_run(
    db: Session, deps: Deps, fake_llm: FakeLLM, world: dict[str, Any]
) -> None:
    fake_llm.script("related_needs", call(1, "update_need", need_id=world["sso"].id, status="shipped"),
                    RelatedNeeds(related=[]))  # fmt: skip
    result = run_agent(db, world["sso"], deps)
    [step] = result.steps
    assert (step.tool, step.status) == ("update_need", "rejected")
    db.refresh(world["sso"])
    assert world["sso"].status == NeedStatus.open
    reply = fake_llm.turns[1]["messages"][-1]["content"][0]
    assert reply["type"] == "tool_result" and reply["tool_use_id"] == "t1" and reply["is_error"] is True
    assert "search_needs" in reply["content"]  # the rejection names what is allowed


def test_bad_arguments_are_an_error_result_not_a_crash(
    db: Session, deps: Deps, fake_llm: FakeLLM, world: dict[str, Any]
) -> None:
    fake_llm.script("related_needs", call(1, "get_need", need_id="not a number"), RelatedNeeds(related=[]))
    result = run_agent(db, world["sso"], deps)
    assert [s.status for s in result.steps] == ["error"]
    assert result.status == "complete"


# --- what the agent reports is verified ---------------------------------------------------------------------


def test_each_related_need_cites_a_request_with_a_verbatim_quote(
    db: Session, deps: Deps, fake_llm: FakeLLM, world: dict[str, Any]
) -> None:
    fake_llm.script(
        "related_needs", RelatedNeeds(related=[found(world, quote="We need SCIM   provisioning from OKTA")])
    )
    [f] = run_agent(db, world["sso"], deps).findings
    assert f.verified and f.problem is None
    assert f.need_title == "IT admins need automatic user provisioning"


def test_a_fabricated_quote_is_caught(
    db: Session, deps: Deps, fake_llm: FakeLLM, world: dict[str, Any]
) -> None:
    fake_llm.script(
        "related_needs", RelatedNeeds(related=[found(world, quote="SCIM is our top priority for 2027")])
    )
    [f] = run_agent(db, world["sso"], deps).findings
    assert not f.verified and "quote" in (f.problem or "")


@pytest.mark.parametrize(
    "change, problem",
    [
        ({"request_id": "okta"}, "request"),  # a request of another need
        ({"need_id": "sso"}, "itself"),
        ({"need_id": 9999}, "need"),
    ],
)
def test_a_finding_that_cites_the_wrong_need_or_request_is_flagged(
    db: Session, deps: Deps, fake_llm: FakeLLM, world: dict[str, Any], change: dict[str, Any], problem: str
) -> None:
    resolved = {k: (world[v].id if isinstance(v, str) else v) for k, v in change.items()}
    fake_llm.script("related_needs", RelatedNeeds(related=[found(world, **resolved)]))
    [f] = run_agent(db, world["sso"], deps).findings
    assert not f.verified and problem in (f.problem or "")


def test_a_merged_need_is_not_a_finding(
    db: Session, deps: Deps, fake_llm: FakeLLM, make: Factory, world: dict[str, Any]
) -> None:
    world["scim"].status, world["scim"].merged_into_id = NeedStatus.merged, world["dark"].id
    make._save(world["scim"])
    fake_llm.script("related_needs", RelatedNeeds(related=[found(world)]))
    [f] = run_agent(db, world["sso"], deps).findings
    assert not f.verified and "merged" in (f.problem or "")


# --- the trajectory is stored -------------------------------------------------------------------------------


def test_the_trajectory_records_each_tool_its_arguments_result_size_and_latency(
    db: Session, deps: Deps, fake_llm: FakeLLM, world: dict[str, Any]
) -> None:
    fake_llm.script("related_needs", call(1, "get_need", need_id=world["scim"].id), RelatedNeeds(related=[]))
    result = run_agent(db, world["sso"], deps)
    [step] = result.steps
    sent = fake_llm.turns[1]["messages"][-1]["content"][0]["content"]
    assert (step.n, step.tool, step.args, step.status) == (1, "get_need", {"need_id": world["scim"].id}, "ok")
    assert step.result_chars == len(sent) > 0 and step.latency_ms >= 0
    first_turn = db.get(AIRun, step.ai_run_id)
    assert first_turn is not None and first_turn.step == "related_needs"
    assert len(result.run_ids) == 2 == len(runs(db, "related_needs"))  # one ai_run per turn


def test_tool_results_reach_the_model_redacted(
    db: Session, deps: Deps, fake_llm: FakeLLM, world: dict[str, Any]
) -> None:
    fake_llm.script("related_needs", call(1, "get_need", need_id=world["sso"].id), RelatedNeeds(related=[]))
    run_agent(db, world["sso"], deps)
    sent = json.dumps(fake_llm.turns[1]["messages"])
    assert "ciso@northwind.example" not in sent and "[email]" in sent


def test_get_need_returns_request_ids_and_texts_and_search_skips_the_need_itself(
    db: Session, deps: Deps, fake_llm: FakeLLM, world: dict[str, Any]
) -> None:
    fake_llm.script("related_needs", call(1, "search_needs", query="Okta single sign-on SAML"),
                    call(2, "get_need", need_id=world["scim"].id), RelatedNeeds(related=[]))  # fmt: skip
    run_agent(db, world["sso"], deps)
    searched = json.loads(_result(fake_llm, 1))
    assert world["sso"].id not in [n["need_id"] for n in searched["needs"]]
    got = json.loads(_result(fake_llm, 2))
    assert got["requests"] == [{"request_id": world["scim_req"].id, "title": "SCIM", "text": SCIM}]


def _result(fake_llm: FakeLLM, turn: int) -> str:
    return str(fake_llm.turns[turn]["messages"][-1]["content"][0]["content"]).replace("&amp;", "&")


# --- the brief survives the agent --------------------------------------------------------------------------


@pytest.mark.parametrize("error", [TerminalError("refused (cyber)"), TransientError("529 overloaded")])
def test_if_the_agent_fails_the_brief_is_still_produced_without_related_needs_and_says_so(
    db: Session, deps: Deps, fake_llm: FakeLLM, world: dict[str, Any], error: Exception
) -> None:
    fake_llm.script("related_needs", error)
    fake_llm.script("decision_brief", brief(world))
    out = build(db, world["sso"].id, deps)
    assert out["related"]["status"] == "unavailable" and str(error) in out["related"]["reason"]
    assert out["brief"]["related_needs"] == [] and out["brief"]["summary"]
    assert "not available" in fake_llm.calls[-1].user  # the brief model is told, so it doesn't guess


def test_if_the_agent_times_out_the_brief_is_still_produced(
    db: Session, deps: Deps, fake_llm: FakeLLM, world: dict[str, Any]
) -> None:
    ticks = itertools.chain([0.0, 0.0], itertools.repeat(500.0))
    fake_llm.script(
        "related_needs", call(1, "search_needs", query="sso"), call(2, "search_needs", query="saml")
    )
    fake_llm.script("decision_brief", brief(world))
    out = build(db, world["sso"].id, deps, clock=lambda: next(ticks))
    assert out["related"]["status"] == "unavailable" and "timed out" in out["related"]["reason"]
    assert out["related"]["findings"] == [] and out["brief"]["recommendation"] == "Plan it."


# --- the brief is verified in code ------------------------------------------------------------------------


def test_money_in_the_brief_comes_from_the_data(
    db: Session, deps: Deps, fake_llm: FakeLLM, world: dict[str, Any]
) -> None:
    made_up = brief(world, summary="SSO protects $9.9M in ARR and $520k from customers.")
    fake_llm.script("decision_brief", made_up, made_up)  # the repair round repeats the made-up figure
    out = build(db, world["sso"].id, deps)
    assert out["facts"]["arr_customers"]["value"] == 520_000
    assert out["facts"]["pipeline_prospects"]["value"] == 250_000
    assert "$9.9M" not in json.dumps(out["brief"])
    assert "$520k" in out["brief"]["summary"]  # a figure that matches the data stays
    check = next(c for c in out["checks"] if c["part"] == "summary")
    assert not check["ok"] and "$9.9M" in check["problem"]


def test_business_impact_shows_the_values_of_the_facts_it_cites(
    db: Session, deps: Deps, fake_llm: FakeLLM, world: dict[str, Any]
) -> None:
    cites = brief(world, business_impact=[
        ImpactClaim(statement="Revenue at stake.", fact_keys=["arr_customers", "pipeline_prospects"]),
        ImpactClaim(statement="Churn risk.", fact_keys=["churn_forecast"]),
    ])  # fmt: skip
    fake_llm.script("decision_brief", cites, cites)  # the unknown key fails again after the repair round
    out = build(db, world["sso"].id, deps)
    first, second = out["brief"]["business_impact"]
    assert [f["display"] for f in first["facts"]] == ["$520,000", "$250,000"]
    assert second["facts"] == []
    bad = next(c for c in out["checks"] if c["part"] == "business_impact[1]")
    assert not bad["ok"] and "churn_forecast" in bad["problem"]


def test_after_one_failed_repair_round_failing_claims_are_shown_flagged(
    db: Session, deps: Deps, fake_llm: FakeLLM, world: dict[str, Any]
) -> None:
    fake = EvidenceQuote(request_id=world["okta"].id, quote="Okta is mandatory for the board")
    bad = brief(
        world, evidence=[EvidenceQuote(request_id=world["okta"].id, quote="need SAML single sign-on"), fake]
    )
    fake_llm.script("decision_brief", bad, bad)
    out = build(db, world["sso"].id, deps)
    assert len(runs(db, "decision_brief")) == 2 and out["repaired"] is True
    assert [e["quote"] for e in out["brief"]["evidence"]] == [
        "need SAML single sign-on",
        "Okta is mandatory for the board",
    ]
    flags = {c["part"]: c["ok"] for c in out["checks"]}
    assert flags["evidence[0]"] is True and flags["evidence[1]"] is False
    assert out["flagged"] == 1
    assert "evidence[1]" in fake_llm.calls[-1].user  # the repair round named the failing claim


def test_a_repair_that_fixes_the_claims_clears_the_flags(
    db: Session, deps: Deps, fake_llm: FakeLLM, world: dict[str, Any]
) -> None:
    wrong = brief(world, evidence=[EvidenceQuote(request_id=world["scim_req"].id, quote="SCIM provisioning")])
    fake_llm.script("decision_brief", wrong, brief(world))
    out = build(db, world["sso"].id, deps)
    assert out["flagged"] == 0 and out["repaired"] is True and all(c["ok"] for c in out["checks"])


def test_a_clean_brief_needs_no_repair(
    db: Session, deps: Deps, fake_llm: FakeLLM, world: dict[str, Any]
) -> None:
    fake_llm.script("decision_brief", brief(world))
    out = build(db, world["sso"].id, deps)
    assert (out["repaired"], out["flagged"]) == (False, 0)
    assert len(runs(db, "decision_brief")) == 1


def test_related_needs_in_the_brief_must_be_verified_findings(
    db: Session, deps: Deps, fake_llm: FakeLLM, world: dict[str, Any]
) -> None:
    fake_llm.script("related_needs", RelatedNeeds(related=[found(world)]))
    claimed = [BriefRelatedNeed(need_id=world["scim"].id, relation="depends_on", why_it_matters="Offboarding."),
               BriefRelatedNeed(need_id=world["dark"].id, relation="overlaps", why_it_matters="Made up.")]  # fmt: skip
    fake_llm.script(
        "decision_brief", brief(world, related_needs=claimed), brief(world, related_needs=claimed)
    )
    out = build(db, world["sso"].id, deps)
    flags = {c["part"]: c["ok"] for c in out["checks"]}
    assert flags["related_needs[0]"] is True and flags["related_needs[1]"] is False
    assert out["related"]["status"] == "complete"
    assert [f["need_id"] for f in out["related"]["findings"]] == [world["scim"].id]


def test_the_brief_is_given_facts_requests_and_goals_but_no_contact_details(
    db: Session, deps: Deps, fake_llm: FakeLLM, world: dict[str, Any]
) -> None:
    fake_llm.script("decision_brief", brief(world))
    build(db, world["sso"].id, deps)
    sent = fake_llm.calls[-1]
    assert sent.step == "decision_brief"
    assert "ciso@northwind.example" not in sent.user and "[email]" in sent.user
    assert "arr_customers" in sent.user and "enterprise_readiness" in sent.user
    assert f'id="{world["okta"].id}"' in sent.user


def test_the_stored_content_has_the_trajectory_and_every_run(
    db: Session, deps: Deps, fake_llm: FakeLLM, world: dict[str, Any]
) -> None:
    fake_llm.script(
        "related_needs", call(1, "get_need", need_id=world["scim"].id), RelatedNeeds(related=[found(world)])
    )
    fake_llm.script("decision_brief", brief(world))
    out = build(db, world["sso"].id, deps)
    [step] = out["related"]["steps"]
    assert set(step) >= {"n", "tool", "args", "status", "result_chars", "latency_ms", "ai_run_id"}
    assert out["related"]["cap"] == 8 and out["related"]["tool_calls"] == 1
    assert len(out["runs"]) == 3  # two agent turns and one brief call
    assert out["model"] == "claude-sonnet-5-5" and out["prompt_version"] == "decision_brief_v1"


# --- offline mode: a baseline, not an agent ---------------------------------------------------------------


@pytest.fixture
def offline(deps: Deps) -> Deps:
    from app.ai.gateway import Gateway, OfflineClient, StepConfig

    steps = {k: StepConfig("offline-baseline", 2000) for k in ("related_needs", "decision_brief")}
    g = Gateway(client=OfflineClient(), steps=steps, prices={"offline-baseline": {"input": 0.0, "output": 0.0}},
                record=deps.gateway.record)  # fmt: skip
    return Deps(gateway=g, search=deps.search, routing=deps.routing, priorities=deps.priorities)


def test_offline_the_baseline_searches_once_reads_the_nearest_need_and_cites_it(
    db: Session, offline: Deps, world: dict[str, Any]
) -> None:
    out = build(db, world["sso"].id, offline)
    rel = out["related"]
    assert [s["tool"] for s in rel["steps"]] == ["search_needs", "get_need"]
    assert rel["status"] == "complete" and rel["model"] == "offline-baseline"
    [f] = rel["findings"]
    assert f["verified"] and f["relation"] == "overlaps" and "baseline" in f["rationale"].lower()


def test_offline_the_template_brief_passes_its_own_checks(
    db: Session, offline: Deps, world: dict[str, Any]
) -> None:
    out = build(db, world["sso"].id, offline)
    assert out["flagged"] == 0 and out["repaired"] is False
    assert out["brief"]["evidence"] and out["brief"]["business_impact"]
    assert "offline" in out["brief"]["confidence_rationale"].lower()


def test_offline_with_no_other_needs_nothing_is_related(db: Session, make: Factory, offline: Deps) -> None:
    acct = make.account("Solo", Segment.smb, arr=9_000)
    need = make.need("Owners need a weekly email digest", persona="smb_owner")
    make.request(
        make.requester(acct), need, "Digest", description="A weekly email.", status=RequestStatus.processed
    )
    offline.search.rebuild(db)
    out = build(db, need.id, offline)  # type: ignore[arg-type]
    assert out["related"]["findings"] == [] and out["related"]["status"] == "complete"


# --- the brief as a markdown file (docs/examples) ---------------------------------------------------------


def test_the_markdown_shows_every_section_its_flags_the_trajectory_and_the_calls(
    db: Session, deps: Deps, fake_llm: FakeLLM, world: dict[str, Any]
) -> None:
    from app.models import Brief
    from app.services.briefs import brief_out, to_markdown

    fake = EvidenceQuote(request_id=world["okta"].id, quote="Okta is mandatory for the board")
    bad = brief(world, evidence=[fake])
    fake_llm.script(
        "related_needs", call(1, "get_need", need_id=world["scim"].id), RelatedNeeds(related=[found(world)])
    )
    fake_llm.script("decision_brief", bad, bad)
    row = Brief(
        need_id=world["sso"].id,
        requested_by="robert",
        status="ready",
        content=build(db, world["sso"].id, deps),
    )
    db.add(row)
    db.commit()
    md = to_markdown(brief_out(db, row), "IT admins need SSO before rollout")
    assert md.startswith("# Decision brief: IT admins need SSO before rollout")
    for heading in ("## Summary", "## Business impact", "## Evidence", "## Related needs", "## Options",
                    "## Recommendation", "## Risks", "## Open questions", "## How this brief was built"):  # fmt: skip
        assert heading in md, heading
    assert "> Okta is mandatory for the board" in md and "Unverified:" in md
    assert "ARR of the customer accounts asking: $520,000" in md
    assert "| 1 | get_need |" in md and "cache read" in md.lower()
    assert "1 of 2 claims unverified" not in md  # counts come from the checks, not hard-coded text
    assert f"{row.content['flagged']} of {len(row.content['checks'])} claims unverified" in md  # type: ignore[index]


# --- review fixes (#24) -------------------------------------------------------------------------------------


def test_a_tool_that_raises_is_an_error_step_and_the_brief_survives(
    db: Session, deps: Deps, fake_llm: FakeLLM, world: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    def broken(*_a: Any, **_k: Any) -> Any:
        raise OSError("embedding model missing")

    monkeypatch.setattr(deps.search, "search", broken)
    fake_llm.script("related_needs", call(1, "search_needs", query="sso"), RelatedNeeds(related=[]))
    result = run_agent(db, world["sso"], deps)
    [step] = result.steps
    assert step.status == "error" and "embedding model missing" in (step.note or "")
    assert result.status == "complete"


def test_accented_text_reaches_the_model_unescaped_so_a_copied_quote_verifies(
    db: Session, deps: Deps, fake_llm: FakeLLM, make: Factory, world: dict[str, Any]
) -> None:
    text = "La mayoría de nuestro equipo no puede “confirmar” el acceso."
    req = make.request(make.requester(make.account("Andes")), world["scim"], "Acceso", description=text,
                       status=RequestStatus.processed)  # fmt: skip
    fake_llm.script("related_needs", call(1, "get_need", need_id=world["scim"].id),
                    RelatedNeeds(related=[found(world, request_id=req.id, quote="La mayoría de nuestro equipo")]))  # fmt: skip
    result = run_agent(db, world["sso"], deps)
    assert "mayoría" in _result(fake_llm, 1) and "\\u00ed" not in _result(fake_llm, 1)
    assert result.findings[0].verified


def test_an_agent_answer_cut_by_max_tokens_is_retried_once_with_a_higher_limit(
    db: Session, deps: Deps, fake_llm: FakeLLM, world: dict[str, Any]
) -> None:
    from app.ai.gateway import MaxTokens

    fake_llm.script("related_needs", MaxTokens(), RelatedNeeds(related=[found(world)]))
    result = run_agent(db, world["sso"], deps)
    assert result.status == "complete" and len(result.findings) == 1
    assert [c.max_tokens for c in fake_llm.calls] == [2000, 4000]
    assert [r.outcome for r in runs(db, "related_needs")] == ["max_tokens", "ok"]


def test_a_failed_repair_call_keeps_the_first_brief_flagged(
    db: Session, deps: Deps, fake_llm: FakeLLM, world: dict[str, Any]
) -> None:
    bad = brief(
        world, evidence=[EvidenceQuote(request_id=world["okta"].id, quote="Okta is mandatory for the board")]
    )
    fake_llm.script("decision_brief", bad, TerminalError("refused (cyber)"))
    out = build(db, world["sso"].id, deps)
    assert out["brief"]["evidence"][0]["quote"] == "Okta is mandatory for the board"
    assert out["flagged"] == 1 and out["repaired"] is False and "refused" in (out["repair_error"] or "")


def test_the_version_with_fewer_failing_claims_is_kept(
    db: Session, deps: Deps, fake_llm: FakeLLM, world: dict[str, Any]
) -> None:
    one_bad = brief(world, summary="Worth $9.9M.")
    worse = brief(world, summary="Worth $9.9M.", recommendation="Grab the $7M.", evidence=[
        EvidenceQuote(request_id=world["okta"].id, quote="made up")])  # fmt: skip
    fake_llm.script("decision_brief", one_bad, worse)
    out = build(db, world["sso"].id, deps)
    assert out["flagged"] == 1 and out["brief"]["recommendation"] == "Plan it."


def test_at_most_25_requests_go_to_the_brief_ranked_by_severity(
    db: Session, deps: Deps, fake_llm: FakeLLM, make: Factory, world: dict[str, Any]
) -> None:
    who = make.requester(make.account("Many"))
    for i in range(30):
        make.request(who, world["sso"], f"ask {i}", description=f"please {i}", status=RequestStatus.processed,
                     severity_signal="blocker" if i == 29 else "nice_to_have")  # fmt: skip
    fake_llm.script("decision_brief", brief(world))
    out = build(db, world["sso"].id, deps)
    sent = fake_llm.calls[-1].inputs["requests"]
    assert len(sent) == 25 and sent[0]["title"] == "ask 29"  # the blocker first
    assert out["facts"]["requests"]["value"] == 33  # the count still covers every request


def test_overlapping_figure_matches_are_removed_once(
    db: Session, deps: Deps, fake_llm: FakeLLM, world: dict[str, Any]
) -> None:
    made_up = brief(world, summary="It protects $ 900k ARR.")
    fake_llm.script("decision_brief", made_up, made_up)
    out = build(db, world["sso"].id, deps)
    assert out["brief"]["summary"] == "It protects [figure removed: not in the data] ARR."  # replaced once


@pytest.mark.parametrize("figure, ok", [("$546k", True), ("$494k", True), ("$547k", False), ("$0.5M", True)])
def test_abbreviated_figures_match_within_5_percent(
    db: Session, deps: Deps, fake_llm: FakeLLM, world: dict[str, Any], figure: str, ok: bool
) -> None:
    claim = brief(world, summary=f"Customers worth {figure} ask for it.")
    fake_llm.script("decision_brief", claim, claim)
    out = build(db, world["sso"].id, deps)
    assert next(c for c in out["checks"] if c["part"] == "summary")["ok"] is ok


def test_a_failing_evidence_quote_never_shows_an_invented_figure(
    db: Session, deps: Deps, fake_llm: FakeLLM, world: dict[str, Any]
) -> None:
    fake = brief(
        world, evidence=[EvidenceQuote(request_id=world["okta"].id, quote="We will pay $2M for this")]
    )
    fake_llm.script("decision_brief", fake, fake)
    out = build(db, world["sso"].id, deps)
    assert "$2M" not in json.dumps(out["brief"])
