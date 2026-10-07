"""The door: needs similar to what the requester types, from embeddings only (spec F1)."""

from fastapi.testclient import TestClient
from sqlmodel import Session

from app.ai.gateway import FakeLLM
from app.ai.pipeline import Deps
from app.models import NeedStatus
from tests.backlog import build
from tests.conftest import Factory, assert_error


def test_similar_needs_come_from_embeddings_only(
    client: TestClient, db: Session, make: Factory, deps: Deps, fake_llm: FakeLLM
) -> None:
    b = build(db, make, deps)
    r = client.get("/needs/similar", params={"q": "single sign-on with Okta"})
    assert r.status_code == 200, r.text
    top = r.json()[0]
    assert (top["need_id"], top["title"], top["persona"]) == (
        b.sso.id,
        "IT admins need single sign-on with Okta",
        "it_admin",
    )
    assert 0 < top["score"] <= 1
    assert fake_llm.calls == []


def test_merged_needs_never_come_back(client: TestClient, db: Session, make: Factory, deps: Deps) -> None:
    b = build(db, make, deps)
    b.sso.status = NeedStatus.merged
    db.add(b.sso)
    db.commit()
    deps.search.rebuild(db)
    ids = [
        n["need_id"] for n in client.get("/needs/similar", params={"q": "single sign-on with Okta"}).json()
    ]
    assert b.sso.id not in ids


def test_too_short_a_query_is_422(client: TestClient) -> None:
    r = client.get("/needs/similar", params={"q": "ab"})
    assert r.status_code == 422
    assert_error(r.json(), "validation_error")
