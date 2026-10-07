"""Contract for the pages (frontend/e2e, test-plan §4): my requests, triage detail, need detail, status, AI Ops.

Shapes here are what the requester portal and the PM workspace are built against.
"""

from datetime import timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session

from app.models import (
    AIRun,
    AISuggestion,
    LinkAction,
    LinkActor,
    LinkEvent,
    NeedStatus,
    RequestStatus,
    Segment,
    StakeholderUpdate,
    SuggestionKind,
    SuggestionState,
    SupportLinkStatus,
    utcnow,
)
from tests.conftest import Factory, assert_error


def _run(db: Session, step: str, model: str = "claude-haiku-4-5", **kw: Any) -> AIRun:
    kw.setdefault("outcome", "ok")
    run = AIRun(step=step, model=model, prompt_version=f"{step}_v1", **kw)
    db.add(run)
    db.commit()
    db.refresh(run)
    return run


@pytest.fixture
def world(db: Session, make: Factory) -> dict[str, Any]:
    north = make.account("Northwind", Segment.enterprise, arr=400_000)
    priya = make.requester(north, "Priya Raman", "IT Director")
    rosa = make.requester(make.account("Tiny Bakery", Segment.smb, arr=3_000), "Rosa Bianchi", "Owner")
    sso = make.need("IT admins need SSO before rollout", persona="it_admin", product_area="security_admin",
                    problem="Users keep separate passwords")  # fmt: skip
    first = make.request(priya, sso, "Okta SSO", description="We standardise on Okta", status=RequestStatus.processed,
                         need_statement="IT admins need SSO", persona="it_admin", product_area="security_admin",
                         problem="separate passwords", severity_signal="blocker", extraction_confidence=0.9,
                         extraction_rationale="Names Okta and SAML", redacted_text="Okta SSO\nWe standardise on Okta")  # fmt: skip
    ex = _run(db, "extract", request_id=first.id, cost_usd=0.002, latency_ms=900)
    created = AISuggestion(request_id=first.id, need_id=sso.id, kind=SuggestionKind.new_need,
                           state=SuggestionState.applied, rationale="No existing need matched", ai_run_id=ex.id)  # fmt: skip
    db.add(created)
    db.add(LinkEvent(action=LinkAction.link, actor=LinkActor.auto, need_id=sso.id, request_id=first.id))  # type: ignore[arg-type]
    second = make.request(priya, sso, "SAML please", status=RequestStatus.processed, persona="it_admin",
                          product_area="security_admin", need_statement="IT admins need SAML")  # fmt: skip
    adj = _run(db, "adjudicate", request_id=second.id, cost_usd=0.004, latency_ms=1500)
    auto = AISuggestion(request_id=second.id, need_id=sso.id, kind=SuggestionKind.duplicate, label="same_need",
                        routing_score=0.95, similarity=0.80, area_match=True, persona_match=True,
                        model_confidence=0.9, rationale="Same SSO need", quotes=["SAML please"],
                        state=SuggestionState.applied, audit_sample=True, ai_run_id=adj.id)  # fmt: skip
    db.add(auto)
    db.add(LinkEvent(action=LinkAction.link, actor=LinkActor.auto, need_id=sso.id, request_id=second.id,  # type: ignore[arg-type]
                     routing_score=0.95))  # fmt: skip
    gray = make.request(rosa, None, "Okta", description="Sign in with Okta", status=RequestStatus.processed)
    base = _run(db, "extract", model="offline-baseline", request_id=gray.id)
    proposed = AISuggestion(request_id=gray.id, need_id=sso.id, kind=SuggestionKind.duplicate, label="similar",
                            routing_score=0.735, similarity=0.735, rationale="Offline baseline: similarity 0.735",
                            state=SuggestionState.proposed, ai_run_id=base.id)  # fmt: skip
    db.add(proposed)
    sup = make.support(
        sso, rosa, SupportLinkStatus.confirmed, why_it_matters="One login", severity="important"
    )
    db.add(StakeholderUpdate(need_id=sso.id, kind="requester_update", requester_id=priya.id, body="SSO is planned",  # type: ignore[arg-type]
                             status="approved", approved_by="pm", approved_at=utcnow()))  # fmt: skip
    db.add(StakeholderUpdate(need_id=sso.id, kind="requester_update", requester_id=priya.id, body="draft",  # type: ignore[arg-type]
                             status="draft"))  # fmt: skip
    db.commit()
    return {"sso": sso, "priya": priya, "rosa": rosa, "first": first, "second": second, "gray": gray,
            "auto": auto, "proposed": proposed, "support": sup, "extract_run": ex, "adjudicate_run": adj}  # fmt: skip


# --- my requests ----------------------------------------------------------------------------------------


def test_my_requests_lists_a_requesters_own_requests_newest_first_with_their_need(
    client: TestClient, world: dict[str, Any], make: Factory
) -> None:
    pending = make.request(world["priya"], None, "Dark mode", created_at=utcnow() + timedelta(minutes=1))
    r = client.get("/requests", params={"requester_id": world["priya"].id})
    assert r.status_code == 200, r.text
    rows = r.json()
    assert [x["title"] for x in rows] == ["Dark mode", "SAML please", "Okta SSO"]
    assert (rows[0]["status"], rows[0]["need"]) == ("pending", None)
    assert rows[1]["need"]["id"] == world["sso"].id and rows[1]["need"]["title"].startswith("IT admins")
    assert pending.id == rows[0]["id"]
    assert client.get("/requests", params={"requester_id": world["rosa"].id}).json()[0]["title"] == "Okta"


def test_my_requests_requires_a_known_requester(client: TestClient) -> None:
    assert client.get("/requests").status_code == 422
    r = client.get("/requests", params={"requester_id": 999})
    assert r.status_code == 422
    assert_error(r.json(), "unknown_requester")


# --- triage ---------------------------------------------------------------------------------------------


def test_triage_items_carry_their_source_and_routing_parts(client: TestClient, world: dict[str, Any]) -> None:
    body = client.get("/triage").json()
    by_id = {i["id"]: i for i in body["items"]}
    gray = by_id[world["proposed"].id]
    assert gray["kind"] == "suggestion"
    assert gray["source"] == {"model": "offline-baseline", "prompt_version": "extract_v1",
                              "ai_run_id": world["proposed"].ai_run_id}  # fmt: skip
    assert gray["routing"]["mode"] == "baseline"
    assert gray["routing"]["similarity"] == pytest.approx(0.735)
    assert (
        gray["request"]["requester_name"] == "Rosa Bianchi"
        and gray["request"]["account_name"] == "Tiny Bakery"
    )
    audit = by_id[world["auto"].id]
    assert audit["kind"] == "audit"
    parts = audit["routing"]
    # 0.5 (same_need) + 0.3 x clip((0.80 - 0.2) / (0.8 - 0.2)) + 0.2 x 1 (conftest routing: s_min 0.2, s_max 0.8)
    assert (parts["mode"], parts["label"], parts["area_match"], parts["persona_match"]) == (
        "llm",
        "same_need",
        True,
        True,
    )
    assert (parts["label_points"], parts["similarity_points"], parts["field_points"]) == pytest.approx(
        (0.5, 0.3, 0.2)
    )
    assert (parts["auto_threshold"], parts["suggest_threshold"]) == (0.9, 0.6)
    assert audit["source"]["model"] == "claude-haiku-4-5"


def test_triage_lists_auto_links_for_undo(client: TestClient, world: dict[str, Any]) -> None:
    auto = client.get("/triage").json()["auto_linked"]
    assert [(a["kind"], a["request"]["id"]) for a in auto] == [("auto_link", world["second"].id)]
    assert auto[0]["need"]["id"] == world["sso"].id and auto[0]["routing_score"] == 0.95
    r = client.post(f"/requests/{world['second'].id}/unlink", json={"by": "pm"})
    assert r.status_code == 200, r.text
    assert client.get("/triage").json()["auto_linked"] == []


# --- need detail ----------------------------------------------------------------------------------------


def test_need_detail_explains_its_origin_analysis_evidence_and_trail(
    client: TestClient, world: dict[str, Any]
) -> None:
    n = client.get(f"/needs/{world['sso'].id}").json()
    assert n["origin"]["created_by"] == "ai"
    assert n["origin"]["source"]["model"] == "claude-haiku-4-5"
    assert n["origin"]["rationale"] == "No existing need matched"
    first = next(r for r in n["requests"] if r["title"] == "Okta SSO")
    a = first["analysis"]
    assert (a["need_statement"], a["persona"], a["severity_signal"], a["confidence"]) == (
        "IT admins need SSO",
        "it_admin",
        "blocker",
        0.9,
    )
    assert a["rationale"] == "Names Okta and SAML" and a["source"]["model"] == "claude-haiku-4-5"
    second = next(r for r in n["requests"] if r["title"] == "SAML please")
    assert (second["link"]["actor"], second["link"]["routing_score"], second["link"]["label"]) == (
        "auto",
        0.95,
        "same_need",
    )
    assert {"quote": "SAML please", "kind": "link", "request_id": world["second"].id, "goal": None} in n[
        "evidence"
    ]
    assert [u["body"] for u in n["updates"]] == ["SSO is planned"]  # drafts are never shown
    kinds = [e["kind"] for e in n["audit_trail"]]
    assert kinds.count("link") == 2 and "ai_run" in kinds
    assert all(
        n["audit_trail"][i]["at"] >= n["audit_trail"][i + 1]["at"] for i in range(len(kinds) - 1)
    )  # newest first


def test_the_pm_sets_a_need_status_and_it_is_on_the_trail(client: TestClient, world: dict[str, Any]) -> None:
    body = {"status": "planned", "reason": "Rollout blocker", "by": "pm"}
    r = client.patch(f"/needs/{world['sso'].id}/status", json=body)
    assert r.status_code == 200, r.text
    n = client.get(f"/needs/{world['sso'].id}").json()
    assert n["status"] == "planned"
    first = n["audit_trail"][0]
    assert (first["kind"], first["actor"]) == ("status", "pm")
    assert "open → planned" in first["summary"] and "Rollout blocker" in first["summary"]


@pytest.mark.parametrize(
    "bad",
    [{"status": "merged", "reason": "x", "by": "pm"}, {"status": "planned", "reason": "x"},
     {"status": "nope", "reason": "x", "by": "pm"}],
)  # fmt: skip
def test_status_changes_are_validated(client: TestClient, world: dict[str, Any], bad: dict[str, str]) -> None:
    assert client.patch(f"/needs/{world['sso'].id}/status", json=bad).status_code == 422


def test_a_merged_need_cannot_change_status(client: TestClient, make: Factory) -> None:
    target = make.need("SSO")
    gone = make.need("SSO again", status=NeedStatus.merged, merged_into_id=target.id)
    r = client.patch(f"/needs/{gone.id}/status", json={"status": "planned", "reason": "x", "by": "pm"})
    assert r.status_code == 409
    assert_error(r.json(), "need_merged")


# --- AI Ops ---------------------------------------------------------------------------------------------


def test_ai_ops_reports_calls_cost_latency_acceptance_false_merges_and_the_success_metrics(
    client: TestClient, world: dict[str, Any], db: Session, make: Factory
) -> None:
    _run(db, "adjudicate", request_id=world["gray"].id, outcome="refusal", cost_usd=0.001, latency_ms=500)
    pid = world["proposed"].id
    assert (
        client.post(f"/triage/{pid}/accept", json={"by": "pm"}).status_code == 200
    )  # 1 accepted, touches gray
    assert (
        client.post(f"/triage/{world['auto'].id}/reject", json={"by": "pm"}).status_code == 200
    )  # audit: false merge
    m = client.get("/metrics").json()
    runs = {(r["step"], r["model"]): r for r in m["runs"]}
    ex = runs[("extract", "claude-haiku-4-5")]
    assert (ex["calls"], ex["ok"], ex["cost_usd"], ex["p50_ms"], ex["p95_ms"]) == (1, 1, 0.002, 900, 900)
    adj = runs[("adjudicate", "claude-haiku-4-5")]
    assert (adj["calls"], adj["ok"], adj["failure_rate"]) == (2, 1, 0.5)
    assert m["totals"]["calls"] == 4 and m["totals"]["cost_usd"] == pytest.approx(0.007)
    assert m["totals"]["processed_requests"] == 3
    assert m["totals"]["cost_per_request"] == pytest.approx(0.007 / 3)
    assert (m["acceptance"]["k"], m["acceptance"]["n"]) == (1, 1)
    fm = m["false_merge"]
    assert (fm["audited"]["k"], fm["audited"]["n"], fm["target"]) == (1, 1, 0.03)
    assert fm["within_target"] is False  # the upper bound of 1/1 is far above 3%
    assert (fm["auto_links"], fm["undone"]) == (1, 1)
    # M1: 3 processed; the first (new need) is untouched, gray (accepted) and second (audit false merge) are not
    assert (m["m1"]["processed"], m["m1"]["untouched"]) == (3, 1)
    assert m["m1"]["pm_minutes_per_100"] == pytest.approx(2 * 100 * 2 / 3)
    # M2: one claim at the door against three new requests; nothing created as new was relinked by a PM
    assert (m["m2"]["claims"], m["m2"]["new_requests"], m["m2"]["deflection"]) == (1, 3, 0.25)
    assert (m["m2"]["new_need_requests"], m["m2"]["relinked_by_pm"], m["m2"]["leakage"]) == (1, 0, 0.0)
    assert (m["m3"]["value"], m["m3"]["completed"], m["m3"]["pending"]) == (
        None,
        0,
        0,
    )  # no status change yet


def test_m1_counts_waiting_and_failed_requests_as_needing_a_pm(
    client: TestClient, world: dict[str, Any], make: Factory
) -> None:
    make.request(
        world["rosa"], None, "broken", status=RequestStatus.needs_review, needs_review_reason="refused"
    )
    m1 = client.get("/metrics").json()["m1"]
    # first: untouched; second: auto-linked, untouched; gray: a suggestion still waiting; broken: needs review
    assert (m1["processed"], m1["untouched"]) == (4, 2)
    nr = client.get("/metrics").json()["needs_review"]
    assert (nr["k"], nr["n"]) == (1, 4)


def test_m2_leakage_counts_a_pm_relink_to_an_existing_need_not_an_undo(
    client: TestClient, world: dict[str, Any], db: Session, make: Factory
) -> None:
    assert client.get("/metrics").json()["m2"]["relinked_by_pm"] == 0
    r = client.post(
        f"/requests/{world['first'].id}/unlink", json={"by": "pm"}
    )  # undoing the need's creator: not leakage
    assert r.status_code == 200
    assert client.get("/metrics").json()["m2"]["relinked_by_pm"] == 0
    other = make.need("Admins need audit logs")
    db.add(LinkEvent(action=LinkAction.link, actor=LinkActor.pm, actor_id="pm", need_id=other.id,  # type: ignore[arg-type]
                     request_id=world["gray"].id))  # a PM moving a new-need request to an existing need  # fmt: skip
    db.commit()
    db.add(AISuggestion(request_id=world["gray"].id, need_id=None, kind=SuggestionKind.new_need,
                        state=SuggestionState.applied))  # gray had started a need of its own  # fmt: skip
    db.commit()
    m2 = client.get("/metrics").json()["m2"]
    assert (m2["relinked_by_pm"], m2["new_need_requests"]) == (1, 2)


@pytest.mark.parametrize(
    ("k", "n", "low", "high"), [(0, 10, 0.0, 0.2775), (10, 10, 0.7225, 1.0), (0, 0, 0.0, 1.0)]
)
def test_wilson_bounds_at_the_edges(k: int, n: int, low: float, high: float) -> None:
    from app.services.metrics import wilson

    lo, hi = wilson(k, n)
    assert lo == pytest.approx(low, abs=1e-4)
    assert hi == pytest.approx(high, abs=1e-4)


def test_an_offline_claim_dispute_shows_baseline_parts_and_its_source(
    client: TestClient, db: Session, make: Factory, deps: Any
) -> None:
    import dataclasses

    from app.ai.baseline import Thresholds
    from app.ai.pipeline import process_claim

    offline = dataclasses.replace(deps, mode="baseline", baseline=Thresholds(auto=0.99, suggest=0.98))
    need = make.need("IT admins need SSO", persona="it_admin", product_area="security_admin")
    sup = make.support(need, make.requester(make.account(), "Rosa"), SupportLinkStatus.claimed,
                       why_it_matters="dark mode would be nice")  # fmt: skip
    offline.search.rebuild(db)
    assert process_claim(db, sup.id, offline) == "disputed"  # type: ignore[arg-type]
    [item] = [i for i in client.get("/triage").json()["items"] if i["kind"] == "claim"]
    assert item["routing"]["mode"] == "baseline"
    assert (item["routing"]["area_match"], item["routing"]["persona_match"]) == (None, None)
    # the extract run behind the decision (offline-baseline in the app; this test's fake client is configured as Haiku)
    assert item["source"]["prompt_version"] == "extract_need_v1" and item["source"]["ai_run_id"] is not None
    assert "new need" not in (item["rationale"] or "") and "claim" in (item["rationale"] or "")


def test_setting_the_same_status_is_refused_and_writes_no_history(
    client: TestClient, world: dict[str, Any]
) -> None:
    r = client.patch(f"/needs/{world['sso'].id}/status", json={"status": "open", "reason": "x", "by": "pm"})
    assert r.status_code == 409
    assert_error(r.json(), "no_change")
    trail = client.get(f"/needs/{world['sso'].id}").json()["audit_trail"]
    assert not [e for e in trail if e["kind"] == "status"]


def test_auto_linked_is_capped_newest_first_with_a_total(client: TestClient, world: dict[str, Any]) -> None:
    body = client.get("/triage").json()
    assert body["auto_linked_total"] == len(body["auto_linked"]) == 1


def test_m1_ignores_informational_related_suggestions(
    client: TestClient, world: dict[str, Any], db: Session
) -> None:
    before = client.get("/metrics").json()["m1"]["untouched"]
    db.add(AISuggestion(request_id=world["first"].id, need_id=world["sso"].id, kind=SuggestionKind.related,
                        label="related", state=SuggestionState.proposed))  # shown on the request, never decided  # fmt: skip
    db.commit()
    assert client.get("/metrics").json()["m1"]["untouched"] == before


def test_ai_ops_reports_queue_depth(client: TestClient, world: dict[str, Any], make: Factory) -> None:
    make.request(world["rosa"], None, "waiting")
    q = client.get("/metrics").json()["queue"]
    assert (q["pending"], q["stuck"], q["needs_review"]) == (1, 0, 0)


def test_ai_ops_reports_tokens_per_step_including_cache_reads(client: TestClient, db: Session) -> None:
    _run(
        db,
        "decision_brief",
        model="claude-sonnet-5-5",
        input_tokens=2000,
        output_tokens=1900,
        cache_write_tokens=2600,
    )
    _run(
        db,
        "decision_brief",
        model="claude-sonnet-5-5",
        input_tokens=2100,
        output_tokens=1800,
        cache_read_tokens=2600,
    )
    [row] = [r for r in client.get("/metrics").json()["runs"] if r["step"] == "decision_brief"]
    assert (row["input_tokens"], row["output_tokens"], row["cache_read_tokens"], row["cache_write_tokens"]) == (
        4100, 3700, 2600, 2600,
    )  # fmt: skip
