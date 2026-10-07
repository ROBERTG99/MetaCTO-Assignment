"""The requester portal API (/portal): what a requester may see, and nothing a PM-only page shows.

No revenue, accounts, breakdowns, request descriptions, other people's reasons, internal notes or audit data.
PM routes keep those, so future auth can guard everything outside /portal.
"""

from typing import Any

from fastapi.testclient import TestClient
from sqlmodel import Session

from app.models import RequestStatus, Segment, StakeholderUpdate, SupportLinkStatus, utcnow
from tests.conftest import Factory

PM_ONLY = (
    "breakdown",
    "accounts",
    "audit_trail",
    "evidence",
    "arr",
    "revenue",
    "why_it_matters",
    "description",
)


def _keys(obj: Any) -> set[str]:
    if isinstance(obj, dict):
        return set(obj) | {k for v in obj.values() for k in _keys(v)}
    if isinstance(obj, list):
        return {k for v in obj for k in _keys(v)}
    return set()


def test_portal_need_page_shows_the_need_supporters_and_my_updates_only(
    client: TestClient, make: Factory, db: Session
) -> None:
    north = make.account("Northwind", Segment.enterprise, arr=400_000)
    priya, rosa = make.requester(north, "Priya Raman"), make.requester(make.account("Bakery"), "Rosa Bianchi")
    need = make.need("IT admins need SSO", problem="Separate passwords")
    make.request(
        priya, need, "Okta SSO", description="call me at ana@example.com", status=RequestStatus.processed
    )
    make.support(
        need, rosa, SupportLinkStatus.confirmed, why_it_matters="our secret plan", severity="blocker"
    )
    for who, kind, body in ((priya, "requester_update", "For Priya"), (rosa, "requester_update", "For Rosa"),
                            (None, "cs_note", "Internal note")):  # fmt: skip
        db.add(StakeholderUpdate(need_id=need.id, kind=kind, requester_id=who.id if who else None, body=body,  # type: ignore[arg-type]
                                 approved_body=body, status="approved", approved_at=utcnow()))  # fmt: skip
    db.commit()
    r = client.get(f"/portal/needs/{need.id}", params={"requester_id": priya.id})
    assert r.status_code == 200, r.text
    body = r.json()
    assert not (_keys(body) & set(PM_ONLY)), _keys(body) & set(PM_ONLY)
    assert (
        "ana@example.com" not in r.text and "our secret plan" not in r.text and "Internal note" not in r.text
    )
    assert [u["body"] for u in body["updates"]] == ["For Priya"]
    assert {s["requester_name"]: (s["severity"], s["link_status"]) for s in body["supporters"]} == {
        "Rosa Bianchi": ("blocker", "confirmed")}  # explicit supports; request authors are under requests  # fmt: skip
    assert [q["title"] for q in body["requests"]] == ["Okta SSO"] and body["requests"][0][
        "requester_name"
    ] == "Priya Raman"
    assert body["origin"]["created_by"] == "ai"
    assert client.get(f"/portal/needs/{need.id}").json()["updates"] == []  # no requester: no updates


def test_portal_list_has_counts_but_no_revenue(client: TestClient, make: Factory) -> None:
    need = make.need("IT admins need SSO")
    make.request(make.requester(make.account(arr=400_000)), need, "Okta SSO", status=RequestStatus.processed)
    r = client.get("/portal/needs", params={"q": "sso"})
    assert r.status_code == 200, r.text
    assert not (_keys(r.json()) & set(PM_ONLY))
    [item] = r.json()["items"]
    assert (item["title"], item["support_count"], item["request_count"]) == ("IT admins need SSO", 1, 1)
