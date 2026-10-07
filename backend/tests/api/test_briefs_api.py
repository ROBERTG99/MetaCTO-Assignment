"""POST /needs/{id}/brief queues a brief (202); the worker builds it; GET /needs/{id}/brief returns the newest."""

from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from app.ai.gateway import FakeLLM, Refused, TerminalError, TransientError
from app.ai.pipeline import Deps
from app.models import Brief, NeedStatus
from app.worker import Worker, WorkerConfig
from tests.backlog import build
from tests.conftest import Factory, assert_error


@pytest.fixture
def b(db: Session, make: Factory, deps: Deps) -> Any:
    return build(db, make, deps)


def work(engine: Any, deps: Deps) -> str | None:
    return Worker(engine, deps, WorkerConfig(backoff_base_seconds=0)).run_once()


def test_asking_for_a_brief_queues_it_and_the_worker_builds_it(
    client: TestClient, engine: Any, deps: Deps, b: Any
) -> None:
    r = client.post(f"/needs/{b.sso.id}/brief", json={"by": "maya"})
    assert r.status_code == 202, r.text
    queued = r.json()
    assert queued["status"] == "pending" and queued["need_id"] == b.sso.id and queued["content"] is None
    assert client.get(f"/needs/{b.sso.id}/brief").json()["status"] == "pending"
    assert work(engine, deps) == f"brief:{queued['id']}"
    done = client.get(f"/needs/{b.sso.id}/brief").json()
    assert done["status"] == "ready" and done["requested_by"] == "maya"
    content = done["content"]
    assert content["brief"]["summary"] and content["related"]["status"] == "complete"
    assert content["prompt_version"] == "decision_brief_v1"


def test_the_newest_brief_is_returned(client: TestClient, engine: Any, deps: Deps, b: Any) -> None:
    first = client.post(f"/needs/{b.sso.id}/brief", json={"by": "maya"}).json()
    work(engine, deps)
    second = client.post(f"/needs/{b.sso.id}/brief", json={"by": "maya"}).json()
    assert second["id"] != first["id"]
    assert client.get(f"/needs/{b.sso.id}/brief").json()["id"] == second["id"]


def test_errors(client: TestClient, db: Session, b: Any) -> None:
    assert client.post("/needs/9999/brief", json={"by": "maya"}).status_code == 404
    none_yet = client.get(f"/needs/{b.dark.id}/brief")
    assert none_yet.status_code == 404
    assert_error(none_yet.json(), "no_brief")
    assert client.post(f"/needs/{b.sso.id}/brief", json={"by": ""}).status_code == 422
    b.dark.status, b.dark.merged_into_id = NeedStatus.merged, b.sso.id
    db.add(b.dark)
    db.commit()
    merged = client.post(f"/needs/{b.dark.id}/brief", json={"by": "maya"})
    assert merged.status_code == 409
    assert_error(merged.json(), "need_merged")


def test_a_brief_already_queued_is_returned_instead_of_a_second_one(client: TestClient, b: Any) -> None:
    first = client.post(f"/needs/{b.sso.id}/brief", json={"by": "maya"})
    again = client.post(f"/needs/{b.sso.id}/brief", json={"by": "maya"})
    assert (first.status_code, again.status_code) == (202, 202)
    assert again.json()["id"] == first.json()["id"]  # a double click spends one brief


def test_a_failed_brief_says_why(
    client: TestClient, db: Session, engine: Any, deps: Deps, fake_llm: FakeLLM, b: Any
) -> None:
    fake_llm.script("decision_brief", TerminalError("refused (cyber)"))
    queued = client.post(f"/needs/{b.sso.id}/brief", json={"by": "maya"}).json()
    work(engine, deps)
    failed = client.get(f"/needs/{b.sso.id}/brief").json()
    assert failed["id"] == queued["id"] and failed["status"] == "failed"
    assert "refused (cyber)" in failed["error"]


def test_a_transient_failure_retries_then_succeeds(
    client: TestClient, db: Session, engine: Any, deps: Deps, fake_llm: FakeLLM, b: Any
) -> None:
    fake_llm.script("decision_brief", TransientError("529 overloaded"))
    client.post(f"/needs/{b.sso.id}/brief", json={"by": "maya"})
    work(engine, deps)
    pending = client.get(f"/needs/{b.sso.id}/brief").json()
    assert pending["status"] == "pending" and "529" in pending["error"]
    work(engine, deps)
    assert client.get(f"/needs/{b.sso.id}/brief").json()["status"] == "ready"
    rows = db.exec(select(Brief)).all()
    assert len(rows) == 1 and rows[0].attempts == 2


def test_a_brief_left_processing_by_a_crash_is_reclaimed(
    client: TestClient, db: Session, engine: Any, deps: Deps, b: Any
) -> None:
    queued = client.post(f"/needs/{b.sso.id}/brief", json={"by": "maya"}).json()
    row = db.get(Brief, queued["id"])
    assert row is not None
    row.status = "processing"  # the worker died mid-brief
    db.add(row)
    db.commit()
    Worker(engine, deps).reclaim_stale(lease_seconds=0)  # what startup does
    assert client.get(f"/needs/{b.sso.id}/brief").json()["status"] == "pending"


def test_every_call_behind_a_brief_is_listed_even_when_it_failed(
    client: TestClient, engine: Any, deps: Deps, fake_llm: FakeLLM, b: Any
) -> None:
    fake_llm.script("decision_brief", Refused("cyber"))
    client.post(f"/needs/{b.sso.id}/brief", json={"by": "maya"})
    work(engine, deps)
    failed = client.get(f"/needs/{b.sso.id}/brief").json()
    assert [(c["step"], c["outcome"]) for c in failed["calls"]] == [
        ("related_needs", "ok"),
        ("decision_brief", "refusal"),
    ]


def test_the_last_ready_brief_stays_reachable_while_a_new_one_builds_or_fails(
    client: TestClient, engine: Any, deps: Deps, fake_llm: FakeLLM, b: Any
) -> None:
    first = client.post(f"/needs/{b.sso.id}/brief", json={"by": "maya"}).json()
    work(engine, deps)
    again = client.post(f"/needs/{b.sso.id}/brief", json={"by": "maya"}).json()
    assert again["status"] == "pending" and again["last_ready"]["id"] == first["id"]
    fake_llm.script("decision_brief", TerminalError("refused (cyber)"))
    work(engine, deps)
    now = client.get(f"/needs/{b.sso.id}/brief").json()
    assert now["status"] == "failed" and now["last_ready"]["id"] == first["id"]
    assert now["last_ready"]["content"]["brief"]["summary"]


def test_two_waiting_briefs_for_one_need_cannot_exist(db: Session, b: Any) -> None:
    from sqlalchemy.exc import IntegrityError

    db.add(Brief(need_id=b.sso.id, requested_by="maya"))
    db.commit()
    db.add(Brief(need_id=b.sso.id, requested_by="omar"))
    with pytest.raises(IntegrityError):
        db.commit()
