"""Contract: POST /requests saves the request and returns before any AI work (CLAUDE.md rule 2)."""

from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from app.models import Request, RequestStatus
from tests.conftest import Factory, assert_error


@pytest.fixture
def payload(make: Factory) -> dict[str, Any]:
    requester = make.requester(make.account())
    return {
        "requester_id": requester.id,
        "title": "Weekly KPI email for our exec team",
        "description": "Our VP doesn't log in. Can Brightboard email her the revenue dashboard every Monday?",
        "source": "portal",
    }


def test_create_returns_201_pending_with_no_ai_fields(client: TestClient, payload: dict[str, Any]) -> None:
    r = client.post("/requests", json=payload)
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["status"] == "pending"
    assert body["title"] == payload["title"]
    assert body["source"] == "portal"
    assert body["need_id"] is None
    assert body["problem"] is None and body["persona"] is None
    assert isinstance(body["id"], int)


def test_create_persists_a_pending_row_for_the_worker(
    client: TestClient, payload: dict[str, Any], db: Session
) -> None:
    created = client.post("/requests", json=payload).json()
    row = db.exec(select(Request).where(Request.id == created["id"])).one()
    assert row.status == RequestStatus.pending
    assert (row.attempts, row.claimed_at, row.need_id) == (0, None, None)
    assert row.account_id is not None  # taken from the requester


@pytest.mark.parametrize(
    ("change", "field"),
    [
        ({"title": None}, "title"),
        ({"title": ""}, "title"),
        ({"title": "   "}, "title"),
        ({"description": "x" * 5001}, "description"),
        ({"source": "twitter"}, "source"),
    ],
    ids=["missing-title", "empty-title", "blank-title", "description-over-5000", "unknown-source"],
)
def test_invalid_input_returns_422_in_our_error_shape(
    client: TestClient, payload: dict[str, Any], change: dict[str, Any], field: str
) -> None:
    body = {**payload, **change}
    if change.get("title", "") is None:
        del body["title"]
    r = client.post("/requests", json=body)
    assert r.status_code == 422, r.text
    assert_error(r.json(), "validation_error")
    assert any(d["field"] == field for d in r.json()["error"]["details"]), r.json()


def test_description_of_exactly_5000_characters_is_accepted(
    client: TestClient, payload: dict[str, Any]
) -> None:
    r = client.post("/requests", json={**payload, "description": "x" * 5000})
    assert r.status_code == 201, r.text


def test_unknown_requester_returns_422(client: TestClient, payload: dict[str, Any]) -> None:
    r = client.post("/requests", json={**payload, "requester_id": 9999})
    assert r.status_code == 422, r.text
    assert_error(r.json(), "unknown_requester")


def test_unknown_requester_error_names_the_field(client: TestClient, payload: dict[str, Any]) -> None:
    r = client.post("/requests", json={**payload, "requester_id": 9999})
    assert [d["field"] for d in r.json()["error"]["details"]] == ["requester_id"]


@pytest.fixture
def staff(make: Factory) -> dict[str, int]:
    prospect = make.account("Vantage Insurance", is_prospect=True, arr=0, pipeline_value=380_000)
    other = make.account("Contoso")
    ae = make.requester(None, "Ryan", "Account Executive")
    customer = make.requester(other, "Megan", "Head of Ecommerce")
    return {"prospect": prospect.id, "other": other.id, "ae": ae.id, "customer": customer.id}  # type: ignore[dict-item]


def test_staff_submit_on_behalf_of_an_account(client: TestClient, staff: dict[str, int]) -> None:
    body = {
        "requester_id": staff["ae"],
        "account_id": staff["prospect"],
        "title": "SSO for Vantage",
        "source": "sales",
    }
    r = client.post("/requests", json=body)
    assert r.status_code == 201, r.text
    assert r.json()["account_id"] == staff["prospect"]


@pytest.mark.parametrize("source", ["sales", "support", "cs"])
def test_staff_must_name_the_account_for_customer_sources(
    client: TestClient, staff: dict[str, int], source: str
) -> None:
    r = client.post("/requests", json={"requester_id": staff["ae"], "title": "SSO", "source": source})
    assert r.status_code == 422, r.text
    assert_error(r.json(), "account_required")


def test_internal_staff_request_may_have_no_account(client: TestClient, staff: dict[str, int]) -> None:
    r = client.post(
        "/requests", json={"requester_id": staff["ae"], "title": "Dark theme", "source": "internal"}
    )
    assert r.status_code == 201, r.text
    assert r.json()["account_id"] is None


def test_customer_cannot_submit_for_another_account(client: TestClient, staff: dict[str, int]) -> None:
    body = {
        "requester_id": staff["customer"],
        "account_id": staff["prospect"],
        "title": "x",
        "source": "portal",
    }
    r = client.post("/requests", json=body)
    assert r.status_code == 422, r.text
    assert_error(r.json(), "account_mismatch")


def test_unknown_account_returns_422(client: TestClient, staff: dict[str, int]) -> None:
    body = {"requester_id": staff["ae"], "account_id": 9999, "title": "x", "source": "sales"}
    r = client.post("/requests", json=body)
    assert r.status_code == 422, r.text
    assert_error(r.json(), "unknown_account")
