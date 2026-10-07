"""Stakeholder updates (spec F7): a status change is a human decision; the AI drafts, code checks, the PM approves.

Nothing goes out on its own: drafts reach the (simulated) outbox only through approval, and approval is
refused while the commitment check flags something the PM didn't commit to.
"""

from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.engine import Engine
from sqlmodel import Session, select

from app.ai.gateway import FakeLLM
from app.ai.pipeline import Deps
from app.ai.schemas import CsNote, RequesterUpdate, UpdateDrafts
from app.models import AIRun, Notification, OutboxMessage, RequestStatus, Segment, SupportLinkStatus
from app.worker import Worker
from tests.conftest import Factory, assert_error


def drafts_from(inputs: dict[str, Any], promise: str = "We will ship it next week.") -> UpdateDrafts:
    return UpdateDrafts(
        requester_updates=[
            RequesterUpdate(
                requester_id=s["requester_id"],
                body=f"Hi {s['name']}, about {s['asked']}: it is planned. {promise}",
            )
            for s in inputs["supporters"]
        ],
        cs_notes=[
            CsNote(account_id=a["account_id"], body=f"{a['name']}: SSO is planned.")
            for a in inputs["accounts"]
        ],
    )


@pytest.fixture
def sso(make: Factory, fake_llm: FakeLLM) -> dict[str, Any]:
    north = make.account("Northwind", Segment.enterprise, arr=400_000)
    bakery = make.account("Tiny Bakery", Segment.smb, arr=3_000)
    blue = make.account("Bluepeak", Segment.mid_market, arr=64_000)
    priya, rosa, dev = (make.requester(north, "Priya Raman", "IT Director"),
                        make.requester(bakery, "Rosa Bianchi", "Owner"), make.requester(blue, "Dev Malhotra", "IT Admin"))  # fmt: skip
    need = make.need("IT admins need SSO before rollout")
    make.request(priya, need, "Okta SSO", status=RequestStatus.processed)
    make.request(priya, need, "SAML please", status=RequestStatus.processed)
    make.request(rosa, need, "Log in with Google", status=RequestStatus.processed)
    make.support(need, dev, SupportLinkStatus.confirmed, why_it_matters="60 users, passwords by hand")
    make.support(need, make.requester(north, "Claimed Only"), SupportLinkStatus.claimed, why_it_matters="x")
    fake_llm.respond("stakeholder_update", drafts_from)
    return {
        "need": need,
        "priya": priya,
        "rosa": rosa,
        "dev": dev,
        "accounts": {north.id, bakery.id, blue.id},
    }


def change(client: TestClient, need_id: int, **body: Any) -> Any:
    body.setdefault("status", "planned")
    body.setdefault("reason", "Enterprise rollouts are blocked without it")
    body.setdefault("by", "pm")
    return client.patch(f"/needs/{need_id}/status", json=body)


def drafted(engine: Engine, deps: Deps) -> str | None:
    """Run the worker until it drafts (requests and claims go first: the fixture's claim is checked before)."""
    w = Worker(engine, deps)
    while (done := w.run_once()) is not None:
        if done.startswith("drafts:"):
            return done
    return None


def updates(client: TestClient, need_id: int) -> dict[str, Any]:
    r = client.get(f"/needs/{need_id}/updates")
    assert r.status_code == 200, r.text
    body: dict[str, Any] = r.json()
    return body


def test_a_status_change_is_saved_at_once_and_drafting_waits_for_the_worker(
    client: TestClient, sso: dict[str, Any], fake_llm: FakeLLM
) -> None:
    r = change(client, sso["need"].id)
    assert r.status_code == 200, r.text
    assert (r.json()["to_status"], r.json()["drafts_status"]) == ("planned", "pending")
    assert client.get(f"/needs/{sso['need'].id}").json()["status"] == "planned"
    assert fake_llm.calls == []  # AI never blocks the decision
    [c] = updates(client, sso["need"].id)["changes"]
    assert (c["reason"], c["updates"]) == ("Enterprise rollouts are blocked without it", [])


def test_the_worker_drafts_a_personal_update_per_supporter_and_a_cs_note_per_account(
    client: TestClient, engine: Engine, deps: Deps, db: Session, sso: dict[str, Any], fake_llm: FakeLLM
) -> None:
    cid = change(client, sso["need"].id).json()["id"]
    assert drafted(engine, deps) == f"drafts:{cid}"
    [call] = [c for c in fake_llm.calls if c.step == "stakeholder_update"]
    assert "Enterprise rollouts are blocked without it" in call.user
    assert "Okta SSO" in call.user and "60 users, passwords by hand" in call.user  # what each one asked for
    assert "Claimed Only" not in call.user  # an unconfirmed claim is not a supporter yet
    [c] = updates(client, sso["need"].id)["changes"]
    assert c["drafts_status"] == "drafted"
    personal = {u["requester_id"]: u for u in c["updates"] if u["kind"] == "requester_update"}
    assert set(personal) == {sso["priya"].id, sso["rosa"].id, sso["dev"].id}
    assert {u["account_id"] for u in c["updates"] if u["kind"] == "cs_note"} == sso["accounts"]
    priya = personal[sso["priya"].id]
    assert "Okta SSO" in priya["body"] and priya["status"] == "draft"
    assert [f["phrase"] for f in priya["flags"]] == ["We will ship", "next week"]
    assert priya["source"]["prompt_version"] == "stakeholder_update_v1"
    assert db.exec(select(OutboxMessage)).all() == []  # nothing goes out on its own
    assert client.get(f"/needs/{sso['need'].id}").json()["updates"] == []
    run = db.exec(select(AIRun).where(AIRun.step == "stakeholder_update")).one()
    assert run.need_id == sso["need"].id


def test_a_flagged_draft_cannot_be_approved_until_the_pm_fixes_it(
    client: TestClient, engine: Engine, deps: Deps, db: Session, sso: dict[str, Any]
) -> None:
    change(client, sso["need"].id)
    drafted(engine, deps)
    [c] = updates(client, sso["need"].id)["changes"]
    uid = next(u["id"] for u in c["updates"] if u["requester_id"] == sso["priya"].id)
    r = client.post(f"/updates/{uid}/approve", json={"by": "pm"})
    assert r.status_code == 409
    assert_error(r.json(), "commitments_flagged")
    fixed = client.patch(
        f"/updates/{uid}",
        json={"body": "Hi Priya, SSO is now planned. We'll share a date once it's set.", "by": "pm"},
    )
    assert fixed.status_code == 200, fixed.text
    assert (fixed.json()["flags"], fixed.json()["edited"]) == ([], True)
    ok = client.post(f"/updates/{uid}/approve", json={"by": "pm"})
    assert ok.status_code == 200, ok.text
    assert (ok.json()["status"], ok.json()["approved_by"]) == ("approved", "pm")
    [msg] = db.exec(select(OutboxMessage)).all()
    assert (msg.update_id, msg.channel, msg.recipient) == (uid, "requester", "Priya Raman")
    shown = client.get(f"/needs/{sso['need'].id}").json()["updates"]
    assert [(u["requester_id"], u["body"]) for u in shown] == [(sso["priya"].id, fixed.json()["body"])]
    assert client.post(f"/updates/{uid}/approve", json={"by": "pm"}).status_code == 409  # once only


def test_approving_every_personal_update_notifies_every_supporter_and_measures_the_loop(
    client: TestClient, engine: Engine, deps: Deps, db: Session, sso: dict[str, Any]
) -> None:
    change(client, sso["need"].id)
    drafted(engine, deps)
    [c] = updates(client, sso["need"].id)["changes"]
    assert client.get("/metrics").json()["m3"]["value"] is None
    for u in c["updates"]:
        client.patch(
            f"/updates/{u['id']}", json={"body": "SSO is planned. We'll confirm a date later.", "by": "pm"}
        )
        assert client.post(f"/updates/{u['id']}/approve", json={"by": "pm"}).status_code == 200
    notified = {n.requester_id: n.notified_at for n in db.exec(select(Notification)).all()}
    assert set(notified) == {sso["priya"].id, sso["rosa"].id, sso["dev"].id}
    assert all(t is not None for t in notified.values())
    assert len(db.exec(select(OutboxMessage)).all()) == 6  # 3 personal updates + 3 CS notes
    m3 = client.get("/metrics").json()["m3"]
    assert m3["value"] is not None and m3["value"] >= 0 and (m3["completed"], m3["pending"]) == (1, 0)


def test_a_date_the_pm_entered_is_not_a_commitment_the_ai_invented(
    client: TestClient, engine: Engine, deps: Deps, sso: dict[str, Any], fake_llm: FakeLLM
) -> None:
    fake_llm.respond("stakeholder_update", lambda i: drafts_from(i, "We will ship it by November 30."))
    change(client, sso["need"].id, target_date="2026-11-30")
    drafted(engine, deps)
    [c] = updates(client, sso["need"].id)["changes"]
    assert c["target_date"] == "2026-11-30"
    assert all(u["flags"] == [] for u in c["updates"])


def test_drafts_must_cover_every_supporter_or_get_one_repair(
    client: TestClient, engine: Engine, deps: Deps, db: Session, sso: dict[str, Any], fake_llm: FakeLLM
) -> None:
    fake_llm.script("stakeholder_update", UpdateDrafts(requester_updates=[], cs_notes=[]))
    change(client, sso["need"].id)
    drafted(engine, deps)
    outcomes = [r.outcome for r in db.exec(select(AIRun).where(AIRun.step == "stakeholder_update")).all()]
    assert outcomes == ["validation_error", "ok"]
    assert len(updates(client, sso["need"].id)["changes"][0]["updates"]) == 6


@pytest.mark.parametrize(
    "body",
    [{"status": "merged", "reason": "x", "by": "pm"}, {"status": "planned", "reason": "", "by": "pm"},
     {"status": "planned", "by": "pm"}, {"status": "planned", "reason": "x"}],
    ids=["merged", "empty-reason", "no-reason", "no-by"],
)  # fmt: skip
def test_a_status_change_needs_a_status_a_reason_and_who(
    client: TestClient, sso: dict[str, Any], body: dict[str, Any]
) -> None:
    assert client.patch(f"/needs/{sso['need'].id}/status", json=body).status_code == 422


def test_the_same_status_or_a_merged_need_is_refused(
    client: TestClient, sso: dict[str, Any], make: Factory
) -> None:
    r = change(client, sso["need"].id, status="open")
    assert r.status_code == 409
    assert_error(r.json(), "no_change")
    from app.models import NeedStatus

    gone = make.need("old", status=NeedStatus.merged, merged_into_id=sso["need"].id)
    assert gone.id is not None
    assert_error(change(client, gone.id).json(), "need_merged")


def test_the_offline_drafter_writes_from_the_reason_and_each_request() -> None:
    from app.ai.gateway import OfflineClient

    inputs = {"need": {"title": "IT admins need SSO"}, "status": "planned", "reason": "Planned for next quarter",
              "target_date": None, "supporters": [{"requester_id": 1, "name": "Priya Raman", "asked": "Okta SSO"}],
              "accounts": [{"account_id": 7, "name": "Northwind", "supporters": ["Priya Raman"]}]}  # fmt: skip
    reply = OfflineClient().complete(step="stakeholder_update", model="offline-baseline", system="", user="",
                                     schema=UpdateDrafts, max_tokens=1, effort=None, inputs=inputs)  # fmt: skip
    out = reply.output
    assert isinstance(out, UpdateDrafts)
    [u] = out.requester_updates
    assert (
        u.requester_id == 1
        and "Okta SSO" in u.body
        and "Planned for next quarter" in u.body
        and "Priya" in u.body
    )
    [n] = out.cs_notes
    assert n.account_id == 7 and "Northwind" in n.body and "planned" in n.body


def _draft_all(client: TestClient, engine: Engine, deps: Deps, need_id: int, **body: Any) -> dict[str, Any]:
    r = change(client, need_id, **body)
    assert r.status_code == 200, r.text
    drafted(engine, deps)
    return next(c for c in updates(client, need_id)["changes"] if c["id"] == r.json()["id"])


def test_a_newer_status_change_supersedes_unsent_drafts(
    client: TestClient, engine: Engine, deps: Deps, sso: dict[str, Any]
) -> None:
    first = _draft_all(client, engine, deps, sso["need"].id)
    second = _draft_all(client, engine, deps, sso["need"].id, status="declined", reason="Not this year")
    old = {
        u["id"]: u
        for c in updates(client, sso["need"].id)["changes"]
        if c["id"] == first["id"]
        for u in c["updates"]
    }
    assert {u["status"] for u in old.values()} == {"superseded"}  # a requester can't be told "planned" now
    uid = next(iter(old))
    assert client.post(f"/updates/{uid}/approve", json={"by": "pm"}).status_code == 409
    assert all(u["status"] == "draft" for u in second["updates"])


def test_a_superseded_drafting_job_makes_no_model_call(
    client: TestClient, engine: Engine, deps: Deps, sso: dict[str, Any], fake_llm: FakeLLM
) -> None:
    change(client, sso["need"].id)
    change(client, sso["need"].id, status="declined", reason="Not this year")  # before the worker ran
    w = Worker(engine, deps)
    while w.run_once():
        pass
    assert len([c for c in fake_llm.calls if c.step == "stakeholder_update"]) == 1
    changes = updates(client, sso["need"].id)["changes"]
    assert [c["drafts_status"] for c in changes] == ["drafted", "superseded"]


def test_the_requester_sees_only_the_approved_copy_and_never_a_cs_note(
    client: TestClient, engine: Engine, deps: Deps, sso: dict[str, Any]
) -> None:
    c = _draft_all(client, engine, deps, sso["need"].id)
    clean = "SSO is planned. We'll confirm a date later."
    for u in c["updates"]:
        client.patch(f"/updates/{u['id']}", json={"body": clean, "by": "pm"})
        assert client.post(f"/updates/{u['id']}/approve", json={"by": "pm"}).status_code == 200
    priya = next(u for u in c["updates"] if u["requester_id"] == sso["priya"].id)
    r = client.patch(f"/updates/{priya['id']}", json={"body": "edited after approval", "by": "pm"})
    assert r.status_code == 409  # approved text is final
    shown = client.get(f"/needs/{sso['need'].id}").json()["updates"]
    assert {u["kind"] for u in shown} == {"requester_update"}  # CS notes stay in the PM view
    assert all(u["body"] == clean for u in shown)


def test_a_discarded_draft_cannot_be_sent_and_does_not_count_as_notified(
    client: TestClient, engine: Engine, deps: Deps, db: Session, sso: dict[str, Any]
) -> None:
    c = _draft_all(client, engine, deps, sso["need"].id)
    personal = [u for u in c["updates"] if u["kind"] == "requester_update"]
    assert client.post(f"/updates/{personal[0]['id']}/discard", json={"by": "pm"}).status_code == 200
    assert client.post(f"/updates/{personal[0]['id']}/approve", json={"by": "pm"}).status_code == 409
    assert client.patch(f"/updates/{personal[0]['id']}", json={"body": "x", "by": "pm"}).status_code == 409
    for u in personal[1:]:
        client.patch(f"/updates/{u['id']}", json={"body": "SSO is planned.", "by": "pm"})
        client.post(f"/updates/{u['id']}/approve", json={"by": "pm"})
    assert len(db.exec(select(Notification)).all()) == len(personal) - 1
    m3 = client.get("/metrics").json()["m3"]
    assert (m3["completed"], m3["not_notified"]) == (1, 1)  # one supporter was never told


def test_a_staff_member_filing_for_two_accounts_gives_a_note_per_account(
    client: TestClient, engine: Engine, deps: Deps, make: Factory, sso: dict[str, Any]
) -> None:
    rep = make.requester(None, "Ryan Cho", "Account Executive")
    vantage = make.account("Vantage", Segment.enterprise, arr=0)
    acme = make.account("Acme", Segment.mid_market, arr=50_000)
    make.request(rep, sso["need"], "SSO for Vantage", account_id=vantage.id, status=RequestStatus.processed)
    make.request(rep, sso["need"], "SSO for Acme", account_id=acme.id, status=RequestStatus.processed)
    c = _draft_all(client, engine, deps, sso["need"].id)
    notes = {u["account_id"] for u in c["updates"] if u["kind"] == "cs_note"}
    assert {vantage.id, acme.id} <= notes


def test_a_failed_drafting_job_keeps_the_status_and_can_be_retried(
    client: TestClient, engine: Engine, deps: Deps, db: Session, sso: dict[str, Any], fake_llm: FakeLLM
) -> None:
    from app.ai.gateway import Refused

    fake_llm.script("stakeholder_update", Refused("other"))
    cid = change(client, sso["need"].id).json()["id"]
    drafted(engine, deps)
    [c] = updates(client, sso["need"].id)["changes"]
    assert (c["drafts_status"], client.get(f"/needs/{sso['need'].id}").json()["status"]) == (
        "failed",
        "planned",
    )
    assert "refused" in (c["drafts_error"] or "")
    assert db.exec(select(AIRun).where(AIRun.step == "stakeholder_update")).first() is not None  # recorded
    r = client.post(f"/needs/{sso['need'].id}/status-changes/{cid}/redraft", json={"by": "pm"})
    assert r.status_code == 200 and r.json()["drafts_status"] == "pending"
    drafted(engine, deps)
    assert updates(client, sso["need"].id)["changes"][0]["drafts_status"] == "drafted"
    assert (
        client.post(f"/needs/{sso['need'].id}/status-changes/{cid}/redraft", json={"by": "pm"}).status_code
        == 409
    )


def test_a_need_with_no_supporters_is_drafted_without_a_model_call(
    client: TestClient, engine: Engine, deps: Deps, make: Factory, fake_llm: FakeLLM
) -> None:
    lonely = make.need("Nobody asked yet")
    c = _draft_all(client, engine, deps, lonely.id)  # type: ignore[arg-type]
    assert (c["drafts_status"], c["updates"]) == ("drafted", [])
    assert [x for x in fake_llm.calls if x.step == "stakeholder_update"] == []


def test_the_offline_worker_drafts_too(
    client: TestClient, engine: Engine, deps: Deps, sso: dict[str, Any]
) -> None:
    import dataclasses

    from app.ai.gateway import OfflineClient

    offline = dataclasses.replace(
        deps, mode="baseline", gateway=dataclasses.replace(deps.gateway, client=OfflineClient())
    )
    c = _draft_all(client, engine, offline, sso["need"].id)
    assert c["drafts_status"] == "drafted" and c["updates"]
    assert all(u["source"]["model"] == "offline-baseline" for u in c["updates"])


def test_m3_is_the_median_over_completed_changes() -> None:
    from datetime import UTC, datetime, timedelta

    from app.services.metrics import m3_from

    t0 = datetime(2026, 10, 1, tzinfo=UTC)
    rows: list[tuple[Any, list[tuple[str, Any]]]] = [  # (change created_at, [(status, approved_at)])
        (t0, [("approved", t0 + timedelta(hours=1)), ("approved", t0 + timedelta(hours=3))]),  # 3 h
        (t0, [("approved", (t0 + timedelta(hours=5)).replace(tzinfo=None))]),  # 5 h, a naive timestamp
        (t0, [("draft", None)]),  # pending
        (t0, [("discarded", None)]),  # nobody told
        (t0, [("superseded", None), ("approved", t0 + timedelta(hours=2))]),  # 2 h: superseded don't count
    ]
    m3 = m3_from(rows)
    assert (m3["value"], m3["completed"], m3["pending"], m3["not_notified"]) == (3 * 3600, 3, 1, 1)
