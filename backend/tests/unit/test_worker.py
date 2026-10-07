"""The database queue (ADR 0007): one row at a time, attempts and last error, backoff, stale reclaim, needs_review."""

from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.engine import Engine
from sqlmodel import Session

from app.ai.gateway import FakeLLM, Refused, TransientError
from app.ai.pipeline import Deps
from app.models import Request, RequestStatus, SupportLinkStatus
from app.worker import Worker
from tests.conftest import Factory

T0 = datetime(2026, 10, 7, 12, 0, tzinfo=UTC)


def fresh(engine: Engine, rid: int) -> Request:
    with Session(engine) as s:
        r = s.get(Request, rid)
        assert r is not None
        return r


def pending(make: Factory, n: int) -> list[int]:
    who = make.requester(make.account())
    ids = [
        make.request(who, None, f"request {i}", created_at=T0 - timedelta(hours=n - i)).id for i in range(n)
    ]
    return [i for i in ids if i is not None]


def test_claims_one_pending_request_at_a_time_oldest_first(engine: Engine, make: Factory, deps: Deps) -> None:
    ids = pending(make, 3)
    assert Worker(engine, deps).run_once(now=T0) == f"request:{ids[0]}"
    assert [fresh(engine, i).status for i in ids] == [
        RequestStatus.processed,
        RequestStatus.pending,
        RequestStatus.pending,
    ]
    assert fresh(engine, ids[0]).attempts == 1


def test_a_transient_failure_records_the_error_and_backs_off(
    engine: Engine, make: Factory, deps: Deps, fake_llm: FakeLLM
) -> None:
    [rid] = pending(make, 1)
    fake_llm.script("extract", TransientError("503 overloaded"))
    w = Worker(engine, deps)
    w.run_once(now=T0)
    r = fresh(engine, rid)
    assert (r.status, r.attempts, r.last_error) == (RequestStatus.pending, 1, "503 overloaded")
    assert r.claimed_at is not None
    assert w.run_once(now=T0 + timedelta(seconds=1)) is None  # backoff: 5 s x 2^1 = 10 s
    assert w.run_once(now=T0 + timedelta(seconds=11)) == f"request:{rid}"
    assert fresh(engine, rid).status == RequestStatus.processed


def test_three_failures_move_the_request_to_needs_review(
    engine: Engine, make: Factory, deps: Deps, fake_llm: FakeLLM
) -> None:
    [rid] = pending(make, 1)
    fake_llm.script(
        "extract", TransientError("timeout"), TransientError("timeout"), TransientError("503 overloaded")
    )
    w = Worker(engine, deps)
    for t in (T0, T0 + timedelta(seconds=11), T0 + timedelta(seconds=40)):
        w.run_once(now=t)
    r = fresh(engine, rid)
    assert (r.status, r.attempts) == (RequestStatus.needs_review, 3)
    assert (
        r.needs_review_reason is not None
        and "3 attempts" in r.needs_review_reason
        and "503" in r.needs_review_reason
    )


def test_a_refusal_goes_straight_to_needs_review(
    engine: Engine, make: Factory, deps: Deps, fake_llm: FakeLLM
) -> None:
    [rid] = pending(make, 1)
    fake_llm.script("extract", Refused("cyber"))
    Worker(engine, deps).run_once(now=T0)
    r = fresh(engine, rid)
    assert (r.status, r.attempts) == (RequestStatus.needs_review, 1)
    assert r.needs_review_reason is not None and "refused" in r.needs_review_reason


def test_startup_reclaims_every_processing_row(engine: Engine, make: Factory, deps: Deps) -> None:
    """One worker: anything left in processing at startup was interrupted, however recent."""
    who = make.requester(make.account())
    old = make.request(
        who, None, "old", status=RequestStatus.processing, claimed_at=T0 - timedelta(minutes=10)
    )
    recent = make.request(
        who, None, "recent", status=RequestStatus.processing, claimed_at=T0 - timedelta(seconds=5)
    )
    assert Worker(engine, deps).reclaim_stale(now=T0, lease_seconds=0) == 2
    assert {fresh(engine, old.id).status, fresh(engine, recent.id).status} == {RequestStatus.pending}  # type: ignore[arg-type]


def test_the_periodic_reclaim_respects_the_lease(engine: Engine, make: Factory, deps: Deps) -> None:
    who = make.requester(make.account())
    stale = make.request(
        who, None, "stale", status=RequestStatus.processing, claimed_at=T0 - timedelta(minutes=11)
    )
    live = make.request(
        who, None, "live", status=RequestStatus.processing, claimed_at=T0 - timedelta(minutes=1)
    )
    assert Worker(engine, deps).reclaim_stale(now=T0) == 1  # default lease 600 s
    assert fresh(engine, stale.id).status == RequestStatus.pending  # type: ignore[arg-type]
    assert fresh(engine, live.id).status == RequestStatus.processing  # type: ignore[arg-type]


def test_an_error_outside_the_pipeline_never_kills_the_loop(
    engine: Engine, deps: Deps, monkeypatch: pytest.MonkeyPatch
) -> None:
    w = Worker(engine, deps)

    def broken(now: object = None) -> None:
        raise RuntimeError("database is locked")

    monkeypatch.setattr(w, "run_once", broken)
    assert w.tick() is None  # logged and swallowed; the loop sleeps and tries again


def test_an_index_failure_after_the_commit_keeps_the_request_processed(
    engine: Engine, make: Factory, deps: Deps, monkeypatch: pytest.MonkeyPatch
) -> None:
    [rid] = pending(make, 1)

    def broken(*_a: object, **_k: object) -> None:
        raise RuntimeError("embedder crashed")

    monkeypatch.setattr(deps.search, "add_request", broken)
    Worker(engine, deps).run_once(now=T0)
    assert fresh(engine, rid).status == RequestStatus.processed


def test_a_provider_outage_never_fails_the_submission(
    client: TestClient, engine: Engine, make: Factory, deps: Deps, fake_llm: FakeLLM
) -> None:
    who = make.requester(make.account())
    fake_llm.script("extract", TransientError("timeout"))
    r = client.post("/requests", json={"requester_id": who.id, "title": "SSO", "source": "portal"})
    assert (r.status_code, r.json()["status"]) == (201, "pending")
    Worker(engine, deps).run_once(now=T0)
    after = fresh(engine, r.json()["id"])
    assert after.status == RequestStatus.pending and after.last_error == "timeout"


def test_claims_are_checked_when_no_request_is_waiting(engine: Engine, make: Factory, deps: Deps) -> None:
    need = make.need("Users want a dark theme")
    who = make.requester(make.account())
    sup = make.support(need, who, SupportLinkStatus.claimed, why_it_matters="dark mode please")
    assert Worker(engine, deps).run_once(now=T0) == f"claim:{sup.id}"
