"""Every failure uses our error shape, including the ones no endpoint raises on purpose."""

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from tests.conftest import assert_error

TOO_BIG = 2**63  # one past SQLite's 64-bit integer


def test_unexpected_error_returns_500_in_our_error_shape(
    engine: object, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.services import needs as service

    def boom(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("database on fire")

    monkeypatch.setattr(service, "list_needs", boom)
    with TestClient(create_app(engine), raise_server_exceptions=False) as client:  # type: ignore[arg-type]
        r = client.get("/needs")
    assert r.status_code == 500
    assert_error(r.json(), "internal_error")
    assert "fire" not in r.text  # internals are logged, not returned


@pytest.mark.parametrize(
    ("method", "url", "body"),
    [
        ("get", f"/needs/{TOO_BIG}", None),
        ("post", f"/needs/{TOO_BIG}/support", {"requester_id": 1, "severity": "blocker"}),
        ("post", "/needs/1/support", {"requester_id": TOO_BIG, "severity": "blocker"}),
        ("post", "/requests", {"requester_id": TOO_BIG, "title": "x", "source": "portal"}),
        ("get", "/needs/0", None),
    ],
    ids=["need-id", "support-need-id", "support-requester-id", "request-requester-id", "zero-id"],
)
def test_out_of_range_ids_return_422(client: TestClient, method: str, url: str, body: object) -> None:
    r = client.request(method, url, json=body)
    assert r.status_code == 422, r.text
    assert_error(r.json(), "validation_error")


def test_wrong_method_returns_405_with_allow_header(client: TestClient) -> None:
    r = client.delete("/needs")
    assert r.status_code == 405
    assert_error(r.json(), "method_not_allowed")
    assert "GET" in r.headers.get("allow", "")


def test_malformed_json_returns_422(client: TestClient) -> None:
    r = client.post("/requests", content=b"{not json", headers={"content-type": "application/json"})
    assert r.status_code == 422
    assert_error(r.json(), "validation_error")
