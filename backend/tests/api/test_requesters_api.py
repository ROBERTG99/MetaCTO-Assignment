"""Contract: GET /requesters, the people the UI's role switcher can act as (spec A3: no auth)."""

from fastapi.testclient import TestClient

from app.models import Segment
from tests.conftest import Factory


def test_lists_requesters_with_their_account_sorted_by_name(client: TestClient, make: Factory) -> None:
    north = make.account("Northwind", Segment.enterprise, arr=400_000)
    make.requester(north, "Priya Raman", "IT Director")
    make.requester(None, "Mia Santos", "Support Lead")  # staff: no account
    r = client.get("/requesters")
    assert r.status_code == 200, r.text
    assert r.json() == [
        {"id": 2, "name": "Mia Santos", "role": "Support Lead", "account_id": None, "account_name": None,
         "segment": None},
        {"id": 1, "name": "Priya Raman", "role": "IT Director", "account_id": north.id,
         "account_name": "Northwind", "segment": "enterprise"},
    ]  # fmt: skip
