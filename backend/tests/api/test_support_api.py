"""Contract: POST /needs/{id}/support is an idempotent requester claim, never a confirmed merge by itself."""

from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from app.models import LinkAction, LinkActor, LinkEvent, NeedStatus, Support
from tests.conftest import Factory, assert_error


@pytest.fixture
def ids(make: Factory) -> dict[str, int]:
    acct = make.account()
    need = make.need()
    return {"need": need.id, "a": make.requester(acct, "Ana").id, "b": make.requester(acct, "Ben").id}  # type: ignore[dict-item]


def support(client: TestClient, need: int, requester: int, **kw: Any) -> Any:
    body = {
        "requester_id": requester,
        "why_it_matters": "Board pack is due on the 5th",
        "severity": "blocker",
        **kw,
    }
    return client.post(f"/needs/{need}/support", json=body)


def test_first_support_is_201_and_stored_as_a_claim(client: TestClient, ids: dict[str, int]) -> None:
    r = support(client, ids["need"], ids["a"])
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["link_status"] == "claimed"
    assert (body["severity"], body["why_it_matters"]) == ("blocker", "Board pack is due on the 5th")


def test_repeat_support_is_idempotent_per_requester_and_need(
    client: TestClient, ids: dict[str, int], db: Session
) -> None:
    first = support(client, ids["need"], ids["a"]).json()
    again = support(client, ids["need"], ids["a"], why_it_matters="Also the audit", severity="important")
    assert again.status_code == 200, again.text
    assert again.json()["id"] == first["id"]
    assert (again.json()["severity"], again.json()["why_it_matters"]) == ("important", "Also the audit")
    assert len(db.exec(select(Support)).all()) == 1
    assert support(client, ids["need"], ids["b"]).status_code == 201  # another requester is a new support


def test_claim_does_not_count_as_support_until_confirmed(client: TestClient, ids: dict[str, int]) -> None:
    support(client, ids["need"], ids["a"])
    need = client.get(f"/needs/{ids['need']}").json()
    assert (need["support_count"], need["claimed_support_count"]) == (0, 1)


def test_claim_records_one_link_event_by_the_requester(
    client: TestClient, ids: dict[str, int], db: Session
) -> None:
    support(client, ids["need"], ids["a"])
    support(client, ids["need"], ids["a"])
    events = db.exec(select(LinkEvent)).all()
    assert len(events) == 1
    e = events[0]
    assert (e.action, e.actor, e.actor_id, e.need_id) == (
        LinkAction.link,
        LinkActor.requester_claim,
        str(ids["a"]),
        ids["need"],
    )
    assert e.support_id is not None and e.routing_score is None


@pytest.mark.parametrize("severity", ["urgent", "workaround", ""])
def test_unknown_severity_returns_422(client: TestClient, ids: dict[str, int], severity: str) -> None:
    r = support(client, ids["need"], ids["a"], severity=severity)
    assert r.status_code == 422, r.text
    assert_error(r.json(), "validation_error")


def test_unknown_need_returns_404(client: TestClient, ids: dict[str, int]) -> None:
    r = support(client, 9999, ids["a"])
    assert r.status_code == 404, r.text
    assert_error(r.json(), "not_found")


def test_unknown_requester_returns_422(client: TestClient, ids: dict[str, int]) -> None:
    r = support(client, ids["need"], 9999)
    assert r.status_code == 422, r.text
    assert_error(r.json(), "unknown_requester")


def test_concurrent_first_supports_return_the_same_support(
    client: TestClient, ids: dict[str, int], db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Double click: another request inserts the row between our lookup and our insert."""
    from app.services import needs as service

    first = support(client, ids["need"], ids["a"]).json()
    monkeypatch.setattr(service, "_find_support", lambda *_args: None)  # this request saw no row
    r = support(client, ids["need"], ids["a"], severity="important")
    assert r.status_code == 200, r.text
    assert r.json()["id"] == first["id"]
    assert len(db.exec(select(Support)).all()) == 1
    assert len(db.exec(select(LinkEvent)).all()) == 1


def test_support_on_a_merged_need_returns_409(client: TestClient, make: Factory, ids: dict[str, int]) -> None:
    merged = make.need("Old copy", status=NeedStatus.merged, merged_into_id=ids["need"])
    r = support(client, merged.id, ids["a"])  # type: ignore[arg-type]
    assert r.status_code == 409, r.text
    assert_error(r.json(), "need_merged")
    assert str(ids["need"]) in r.json()["error"]["message"]


def test_repeat_without_why_keeps_the_stored_reason(client: TestClient, ids: dict[str, int]) -> None:
    support(client, ids["need"], ids["a"])
    r = client.post(f"/needs/{ids['need']}/support", json={"requester_id": ids["a"], "severity": "important"})
    assert r.status_code == 200, r.text
    assert (r.json()["severity"], r.json()["why_it_matters"]) == ("important", "Board pack is due on the 5th")
