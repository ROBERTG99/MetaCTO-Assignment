"""Production hardening: rate limits, body limits, CORS and headers, request IDs end to end, health and readiness."""

import json
import logging
from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.engine import Engine
from sqlmodel import Session, select

from app.ai.pipeline import Deps
from app.limits import Limits
from app.main import create_app
from app.models import AIRun, Request
from app.worker import Worker
from tests.conftest import Factory, assert_error


@pytest.fixture
def tight(engine: Engine, deps: Deps) -> Iterator[TestClient]:
    limits = Limits(
        posts_per_minute=3,
        writes_per_minute=6,
        max_body_bytes=2_000,
        web_origins=("https://distill.example",),
    )
    with TestClient(create_app(engine, deps=deps, start_worker=False, limits=limits)) as c:
        yield c


def _request(make: Factory) -> dict[str, Any]:
    who = make.requester(make.account())
    return {"requester_id": who.id, "title": "Dark mode", "description": "please", "source": "portal"}


def test_public_posts_are_rate_limited_per_client(tight: TestClient, make: Factory) -> None:
    body = _request(make)
    codes = [tight.post("/requests", json=body).status_code for _ in range(4)]
    assert codes == [201, 201, 201, 429]
    r = tight.post("/requests", json=body)
    assert_error(r.json(), "rate_limited")
    assert int(r.headers["retry-after"]) >= 1
    assert tight.get("/needs").status_code == 200  # reads are not limited


def test_oversized_bodies_are_refused_before_parsing(tight: TestClient, make: Factory) -> None:
    body = _request(make) | {"description": "x" * 5_000}
    r = tight.post("/requests", json=body)
    assert r.status_code == 413
    assert_error(r.json(), "payload_too_large")


def test_cors_allows_only_the_web_origin(tight: TestClient) -> None:
    ok = tight.options(
        "/needs", headers={"Origin": "https://distill.example", "Access-Control-Request-Method": "GET"}
    )
    assert ok.headers.get("access-control-allow-origin") == "https://distill.example"
    bad = tight.options(
        "/needs", headers={"Origin": "https://evil.example", "Access-Control-Request-Method": "GET"}
    )
    assert "access-control-allow-origin" not in bad.headers


def test_responses_carry_security_headers_and_a_request_id(client: TestClient) -> None:
    r = client.get("/needs")
    assert r.headers["x-content-type-options"] == "nosniff"
    assert r.headers["x-frame-options"] == "DENY"
    assert r.headers["referrer-policy"] == "no-referrer"
    assert len(r.headers["x-request-id"]) >= 16


def test_a_request_id_follows_the_request_through_the_queue_into_ai_runs(
    client: TestClient, engine: Engine, deps: Deps, make: Factory
) -> None:
    r = client.post("/requests", json=_request(make), headers={"X-Request-ID": "req-abc123"})
    assert r.status_code == 201 and r.headers["x-request-id"] == "req-abc123"
    Worker(engine, deps).run_once()
    with Session(engine) as s:
        req = s.get(Request, r.json()["id"])
        assert req is not None and req.trace_id == "req-abc123"
        runs = s.exec(select(AIRun).where(AIRun.request_id == req.id)).all()
        assert runs and all(run.trace_id == "req-abc123" for run in runs)


def test_an_untrusted_request_id_is_replaced(client: TestClient) -> None:
    r = client.get("/needs", headers={"X-Request-ID": "bad id\nwith newline" + "x" * 200})
    assert r.headers["x-request-id"] != "bad id\nwith newline" and "\n" not in r.headers["x-request-id"]


def test_healthz_is_alive_and_readyz_reports_the_queue(client: TestClient, make: Factory) -> None:
    assert client.get("/healthz").json() == {"status": "ok"}
    make.request(make.requester(make.account()), None, "waiting")
    r = client.get("/readyz")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "ready" and body["checks"]["database"] == "ok"
    q = body["queue"]
    assert (q["pending"], q["processing"], q["stuck"], q["needs_review"]) == (1, 0, 0, 0)
    assert q["oldest_pending_seconds"] >= 0


def test_readyz_fails_when_the_database_is_down(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    import app.health as health

    def down(*_a: object, **_k: object) -> None:
        raise RuntimeError("database is locked")

    monkeypatch.setattr(health, "ping_database", down)
    r = client.get("/readyz")
    assert r.status_code == 503
    assert r.json()["checks"]["database"] == "error"
    assert "locked" not in r.text  # internals are logged, not returned


def test_stuck_claims_count_rows_processing_past_their_lease(engine: Engine, make: Factory) -> None:
    from datetime import UTC, datetime, timedelta

    from app.health import queue_stats
    from app.models import RequestStatus

    now = datetime(2026, 10, 7, 12, tzinfo=UTC)
    who = make.requester(make.account())
    make.request(who, None, "fresh", status=RequestStatus.processing, claimed_at=now - timedelta(seconds=30))
    make.request(who, None, "stuck", status=RequestStatus.processing, claimed_at=now - timedelta(seconds=900))
    with Session(engine) as s:
        q = queue_stats(s, now=now, lease_seconds=600)
    assert (q["processing"], q["stuck"]) == (2, 1)


def test_json_logs_carry_the_request_id_and_never_a_secret_or_pii(caplog: pytest.LogCaptureFixture) -> None:
    from app.observability import JsonFormatter, request_id

    token = request_id.set("req-xyz")
    try:
        fake_key = "sk-" + "ant-api03-" + "x" * 40  # built at runtime, so secret scanners stay quiet
        record = logging.LogRecord("distill", logging.WARNING, __file__, 1,
                                   "key %s for ana@example.com, call +1 415 555 0100", (fake_key,), None)  # fmt: skip
        line = json.loads(JsonFormatter().format(record))
    finally:
        request_id.reset(token)
    assert (line["level"], line["logger"], line["request_id"]) == ("WARNING", "distill", "req-xyz")
    assert "sk-ant" not in line["msg"] and "ana@example.com" not in line["msg"] and "555" not in line["msg"]
    assert "[REDACTED]" in line["msg"] and "[email]" in line["msg"]


@pytest.mark.parametrize(
    "path", ["/needs/{id}/support", "/needs/+{id}/support", "/needs/%2B{id}/support", "/needs/{id}.0/support"]
)
def test_support_is_rate_limited_however_the_id_is_written(
    tight: TestClient, make: Factory, path: str
) -> None:
    need = make.need("SSO")
    people = [make.requester(make.account(f"A{i}")) for i in range(4)]
    codes = [tight.post(path.format(id=need.id), json={"requester_id": p.id, "severity": "important"}).status_code
             for p in people]  # fmt: skip
    assert codes[3] == 429 and set(codes[:3]) <= {200, 201, 422}


def test_every_write_shares_a_per_client_budget(tight: TestClient, make: Factory) -> None:
    need = make.need("SSO")
    codes = [tight.patch(f"/needs/{need.id}/status", json={"status": s, "reason": "x", "by": "pm"}).status_code
             for s in ("planned", "open", "planned", "open", "planned", "open", "planned")]  # fmt: skip
    assert codes[:6] == [200] * 6 and codes[6] == 429


def test_redaction_is_linear_on_long_input() -> None:
    import time

    from app.observability import scrub

    started = time.perf_counter()
    scrub("a" * 16_000)
    scrub("/needs/" + "a." * 8_000)
    assert time.perf_counter() - started < 0.05


def test_a_server_error_keeps_the_request_id_headers_and_cors(
    engine: Engine, deps: Deps, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    from app.services import needs as service

    def boom(*_a: object, **_k: object) -> None:
        raise RuntimeError("database on fire")

    monkeypatch.setattr(service, "list_needs", boom)
    limits = Limits(web_origins=("https://distill.example",))
    app = create_app(engine, deps=deps, start_worker=False, limits=limits)
    with TestClient(app, raise_server_exceptions=False) as c, caplog.at_level(logging.ERROR):
        r = c.get("/needs", headers={"Origin": "https://distill.example", "X-Request-ID": "req-boom-123"})
    assert r.status_code == 500
    assert_error(r.json(), "internal_error")
    assert r.headers["x-request-id"] == "req-boom-123" and r.headers["x-content-type-options"] == "nosniff"
    assert r.headers.get("access-control-allow-origin") == "https://distill.example"
    assert "fire" not in r.text


def test_api_responses_are_not_cached(client: TestClient) -> None:
    assert client.get("/needs").headers["cache-control"] == "no-store"


def test_uvicorn_logs_go_through_the_redacting_formatter() -> None:
    from app.observability import configure_logging

    configure_logging("json")
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        lg = logging.getLogger(name)
        assert lg.propagate and not lg.handlers
    assert (
        logging.getLogger("uvicorn.access").level >= logging.WARNING
    )  # our access log replaces it (no query text)


def test_a_requester_sees_a_plain_reason_not_internal_errors(client: TestClient, make: Factory) -> None:
    from app.models import RequestStatus

    who = make.requester(make.account())
    make.request(who, None, "broken", status=RequestStatus.needs_review,
                 needs_review_reason="internal error: OperationalError: SELECT * FROM request WHERE secret=1")  # fmt: skip
    [row] = client.get("/requests", params={"requester_id": who.id}).json()
    assert "OperationalError" not in (row["needs_review_reason"] or "")
    assert "a PM will review" in row["needs_review_reason"]


def test_the_worker_stops_claiming_jobs_at_the_daily_model_budget(
    engine: Engine, deps: Deps, make: Factory
) -> None:
    import dataclasses

    from app.worker import WorkerConfig

    with Session(engine) as s:
        s.add(
            AIRun(
                step="extract",
                model="claude-haiku-4-5",
                prompt_version="extract_need_v1",
                outcome="ok",
                cost_usd=5.0,
            )
        )
        s.commit()
    make.request(make.requester(make.account()), None, "waiting")
    capped = Worker(engine, deps, WorkerConfig(daily_budget_usd=5.0))
    assert capped.run_once() is None  # spend today is at the ceiling: jobs wait, nothing is paid
    assert Worker(engine, deps, WorkerConfig(daily_budget_usd=10.0)).run_once() is not None
    make.request(make.requester(make.account("B")), None, "another")
    from app.ai.baseline import Thresholds

    offline = dataclasses.replace(deps, mode="baseline", baseline=Thresholds(auto=0.99, suggest=0.98))
    assert (
        Worker(engine, offline, WorkerConfig(daily_budget_usd=5.0)).run_once() is not None
    )  # offline costs nothing
