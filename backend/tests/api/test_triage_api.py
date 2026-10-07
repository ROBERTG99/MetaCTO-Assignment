"""The PM inbox: suggestions, claim disputes, the audit sample, failures; accept, reject and undo."""

from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, col, select

from app.ai.pipeline import Deps
from app.models import (
    AISuggestion,
    LinkAction,
    LinkActor,
    LinkEvent,
    Need,
    NeedStatus,
    Request,
    RequestStatus,
    SuggestionKind,
    SuggestionState,
    Support,
    SupportLinkStatus,
)  # fmt: skip
from tests.backlog import SSO_TEXT, build
from tests.conftest import Factory, assert_error


@pytest.fixture
def inbox(db: Session, make: Factory, deps: Deps) -> dict[str, Any]:
    b = build(db, make, deps)

    def req(title: str, need: Need | None = None, statement: str = "Ops need a thing", **kw: Any) -> Request:
        return make.request(b.it, need, title, status=RequestStatus.processed, need_statement=statement, **kw)

    gray = req(SSO_TEXT[0], description=SSO_TEXT[1])
    auto = req("Okta login", b.sso, statement="IT admins need Okta login")
    audited = req("SAML please", b.sso, statement="IT admins need SAML")
    failed = make.request(
        b.it, None, "broken", status=RequestStatus.needs_review, needs_review_reason="refused (cyber)"
    )
    sup = make.support(b.sso, b.smb, SupportLinkStatus.disputed, why_it_matters="dark please")

    def sug(**kw: Any) -> AISuggestion:
        s = AISuggestion(
            kind=SuggestionKind.duplicate, label="same_need", routing_score=0.8, rationale="r", **kw
        )
        db.add(s)
        db.commit()
        db.refresh(s)
        return s

    ids = {
        "gray": sug(request_id=gray.id, need_id=b.sso.id, state=SuggestionState.proposed).id,
        "auto": sug(request_id=auto.id, need_id=b.sso.id, state=SuggestionState.applied).id,
        "audit": sug(
            request_id=audited.id, need_id=b.sso.id, state=SuggestionState.applied, audit_sample=True
        ).id,
        "claim": sug(support_id=sup.id, need_id=b.dark.id, state=SuggestionState.proposed).id,
        "related": sug(
            request_id=gray.id,
            need_id=b.dark.id,
            state=SuggestionState.proposed,
        ).id,
    }
    db.get(AISuggestion, ids["related"]).kind = SuggestionKind.related  # type: ignore[union-attr]
    db.commit()
    assert b.sso.id is not None
    for r in (auto, audited):
        db.add(
            LinkEvent(
                action=LinkAction.link,
                actor=LinkActor.auto,
                need_id=b.sso.id,
                request_id=r.id,
                routing_score=0.95,
            )
        )
    db.commit()
    return {
        "b": b,
        "ids": ids,
        "gray": gray.id,
        "auto": auto.id,
        "audited": audited.id,
        "failed": failed.id,
        "sup": sup.id,
    }


def test_inbox_lists_suggestions_claims_audit_and_failures(client: TestClient, inbox: dict[str, Any]) -> None:
    body = client.get("/triage").json()
    kinds = sorted((i["kind"], i["id"]) for i in body["items"])
    ids = inbox["ids"]
    assert kinds == sorted([("suggestion", ids["gray"]), ("claim", ids["claim"]), ("audit", ids["audit"])])
    item = next(i for i in body["items"] if i["id"] == ids["gray"])
    assert item["request"]["title"] == SSO_TEXT[0] and item["need"]["title"].startswith("IT admins")
    assert [r["id"] for r in body["needs_review"]] == [inbox["failed"]]
    assert body["needs_review"][0]["reason"] == "refused (cyber)"


def test_accepting_a_suggestion_links_and_records_the_pm(
    client: TestClient, db: Session, inbox: dict[str, Any]
) -> None:
    sid = inbox["ids"]["gray"]
    r = client.post(f"/triage/{sid}/accept", json={"by": "maya"})
    assert r.status_code == 200, r.text
    req = db.get(Request, inbox["gray"])
    db.refresh(req)
    assert req.need_id == inbox["b"].sso.id  # type: ignore[union-attr]
    [e] = db.exec(select(LinkEvent).where(LinkEvent.request_id == inbox["gray"])).all()
    assert (e.action, e.actor, e.actor_id) == (LinkAction.link, LinkActor.pm, "maya")
    again = client.post(f"/triage/{sid}/accept", json={"by": "maya"})
    assert again.status_code == 409
    assert_error(again.json(), "not_pending")


def test_rejecting_a_suggestion_makes_the_request_its_own_need(
    client: TestClient, db: Session, inbox: dict[str, Any]
) -> None:
    r = client.post(f"/triage/{inbox['ids']['gray']}/reject", json={"by": "maya"})
    assert r.status_code == 200, r.text
    req = db.get(Request, inbox["gray"])
    db.refresh(req)
    need = db.get(Need, req.need_id)  # type: ignore[union-attr]
    assert need is not None and need.title == "Ops need a thing" and need.id != inbox["b"].sso.id


def test_claims_are_confirmed_or_rejected(client: TestClient, db: Session, inbox: dict[str, Any]) -> None:
    assert client.post(f"/triage/{inbox['ids']['claim']}/accept", json={"by": "maya"}).status_code == 200
    sup = db.get(Support, inbox["sup"])
    db.refresh(sup)
    assert sup.link_status == SupportLinkStatus.confirmed  # type: ignore[union-attr]


def test_audit_verdicts(client: TestClient, db: Session, inbox: dict[str, Any]) -> None:
    sid = inbox["ids"]["audit"]
    assert client.post(f"/triage/{sid}/reject", json={"by": "maya"}).status_code == 200
    sug = db.get(AISuggestion, sid)
    db.refresh(sug)
    assert (sug.audit_verdict, sug.state) == ("false_merge", SuggestionState.undone)  # type: ignore[union-attr]
    req = db.get(Request, inbox["audited"])
    db.refresh(req)
    assert req.need_id != inbox["b"].sso.id  # type: ignore[union-attr]
    reasons = [
        e.reason for e in db.exec(select(LinkEvent).where(LinkEvent.request_id == inbox["audited"])).all()
    ]
    assert "audit: false_merge" in reasons


def test_undo_restores_the_request_as_its_own_need(
    client: TestClient, db: Session, deps: Deps, inbox: dict[str, Any]
) -> None:
    r = client.post(f"/requests/{inbox['auto']}/unlink", json={"by": "maya"})
    assert r.status_code == 200, r.text
    req = db.get(Request, inbox["auto"])
    db.refresh(req)
    need = db.get(Need, req.need_id)  # type: ignore[union-attr]
    assert need is not None and need.title == "IT admins need Okta login" and need.id == r.json()["need_id"]
    trail = db.exec(
        select(LinkEvent).where(LinkEvent.request_id == inbox["auto"]).order_by(col(LinkEvent.id))
    ).all()
    assert [(e.action, e.actor, e.actor_id, e.need_id) for e in trail[-2:]] == [
        (LinkAction.unlink, LinkActor.pm, "maya", inbox["b"].sso.id),
        (LinkAction.link, LinkActor.pm, "maya", need.id),
    ]
    assert trail[-2].reason == "undo"
    sug = db.get(AISuggestion, inbox["ids"]["auto"])
    db.refresh(sug)
    assert sug.state == SuggestionState.undone and sug.decided_by == "maya"  # type: ignore[union-attr]
    assert deps.search.search("Okta login")[0][0] == need.id  # the index follows the move


def test_undo_errors(client: TestClient, inbox: dict[str, Any]) -> None:
    r = client.post(f"/requests/{inbox['gray']}/unlink", json={"by": "maya"})  # not linked to anything
    assert r.status_code == 409
    assert_error(r.json(), "not_linked")
    assert client.post("/requests/9999/unlink", json={"by": "maya"}).status_code == 404
    assert client.post(f"/requests/{inbox['auto']}/unlink", json={"by": ""}).status_code == 422


def test_a_second_decision_on_the_same_suggestion_is_409(
    client: TestClient, db: Session, inbox: dict[str, Any]
) -> None:
    sid = inbox["ids"]["gray"]
    needs_before = len(db.exec(select(Need)).all())
    assert client.post(f"/triage/{sid}/reject", json={"by": "maya"}).status_code == 200
    second = client.post(f"/triage/{sid}/reject", json={"by": "maya"})
    assert second.status_code == 409
    assert len(db.exec(select(Need)).all()) == needs_before + 1  # one new need, not two


def test_undo_of_a_request_that_is_already_alone_is_409(client: TestClient, inbox: dict[str, Any]) -> None:
    first = client.post(f"/requests/{inbox['auto']}/unlink", json={"by": "maya"})
    assert first.status_code == 200
    again = client.post(f"/requests/{inbox['auto']}/unlink", json={"by": "maya"})
    assert again.status_code == 409
    assert_error(again.json(), "already_alone")


def test_undoing_an_audited_link_records_a_false_merge(
    client: TestClient, db: Session, inbox: dict[str, Any]
) -> None:
    assert client.post(f"/requests/{inbox['audited']}/unlink", json={"by": "maya"}).status_code == 200
    sug = db.get(AISuggestion, inbox["ids"]["audit"])
    db.refresh(sug)
    assert (sug.audit_verdict, sug.decided_by) == ("false_merge", "maya")  # type: ignore[union-attr]


def test_accepting_into_a_merged_need_follows_the_merge(
    client: TestClient, db: Session, inbox: dict[str, Any]
) -> None:
    b = inbox["b"]
    b.sso.status, b.sso.merged_into_id = NeedStatus.merged, b.dark.id
    db.add(b.sso)
    db.commit()
    assert client.post(f"/triage/{inbox['ids']['gray']}/accept", json={"by": "maya"}).status_code == 200
    req = db.get(Request, inbox["gray"])
    db.refresh(req)
    assert req.need_id == b.dark.id  # type: ignore[union-attr]


def test_rejecting_a_claim_unlinks_it(client: TestClient, db: Session, inbox: dict[str, Any]) -> None:
    item = next(i for i in client.get("/triage").json()["items"] if i["kind"] == "claim")
    assert item["alternative_need"]["id"] == inbox["b"].dark.id  # what the model would pick instead
    assert item["support"]["claimed_need"]["id"] == inbox["b"].sso.id  # what accept would confirm
    assert client.post(f"/triage/{inbox['ids']['claim']}/reject", json={"by": "maya"}).status_code == 200
    sup = db.get(Support, inbox["sup"])
    db.refresh(sup)
    assert sup.link_status == SupportLinkStatus.rejected  # type: ignore[union-attr]
    [e] = db.exec(select(LinkEvent).where(LinkEvent.support_id == inbox["sup"])).all()
    assert (e.action, e.actor, e.actor_id) == (LinkAction.unlink, LinkActor.pm, "maya")


def test_a_need_emptied_by_a_false_merge_sends_pending_suggestions_nowhere(
    client: TestClient, db: Session, make: Factory, inbox: dict[str, Any]
) -> None:
    it = inbox["b"].it
    n = make.need("Ops need audit logs")
    a = make.request(
        it, n, "Audit logs", status=RequestStatus.processed, need_statement="Ops need audit logs"
    )
    b = make.request(
        it, n, "Login history", status=RequestStatus.processed, need_statement="Ops need history"
    )
    c = make.request(
        it, None, "Who changed what", status=RequestStatus.processed, need_statement="Ops need logs"
    )
    sampled = AISuggestion(kind=SuggestionKind.duplicate, label="same_need", routing_score=0.9, rationale="r",
                           request_id=b.id, need_id=n.id, state=SuggestionState.applied, audit_sample=True)  # fmt: skip
    pending = AISuggestion(kind=SuggestionKind.duplicate, label="same_need", routing_score=0.6, rationale="r",
                           request_id=c.id, need_id=n.id, state=SuggestionState.proposed)  # fmt: skip
    db.add_all([sampled, pending])
    db.commit()
    assert client.post(f"/requests/{a.id}/unlink", json={"by": "maya"}).status_code == 200  # n holds only b
    assert client.post(f"/triage/{sampled.id}/reject", json={"by": "maya"}).status_code == 200  # n is emptied
    r = client.post(f"/triage/{pending.id}/accept", json={"by": "maya"})
    assert r.status_code == 409  # not silently linked to b's unrelated new need
    assert_error(r.json(), "need_gone")
    db.refresh(c)
    assert c.need_id is None
