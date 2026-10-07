"""Contract: GET /needs (search, filters, sorting, pagination) and GET /needs/{id}."""

from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.models import NeedStatus, Segment, SupportLinkStatus
from tests.conftest import Factory, assert_error, days_ago


@pytest.fixture
def backlog(make: Factory) -> dict[str, Any]:
    ent = make.account("Northwind", Segment.enterprise, arr=400_000)
    mid = make.account("Contoso", Segment.mid_market, arr=60_000)
    smb = make.account("Tiny Bakery", Segment.smb, arr=3_000)
    ana, ben, cy = (
        make.requester(ent, "Ana", "IT Director"),
        make.requester(mid, "Ben", "Controller"),
        make.requester(smb, "Cy", "Owner"),
    )

    sso = make.need("IT admins need SSO before rollout", product_area="security")
    excel = make.need("Finance needs month-end data in Excel", product_area="reporting")
    dark = make.need("SMB users want a dark theme", product_area="ui", status=NeedStatus.planned)
    gone = make.need("Old duplicate of SSO", product_area="security", status=NeedStatus.merged)

    make.request(ana, sso, "Okta SSO please", created_at=days_ago(30))
    make.request(ben, sso, "Azure AD login", created_at=days_ago(20))
    make.request(ben, excel, "Monthly finance pack to xlsx", created_at=days_ago(2))
    make.request(cy, dark, "dark mode!!", created_at=days_ago(10))
    make.support(sso, cy, SupportLinkStatus.confirmed, why_it_matters="Security asked")
    make.support(dark, ana, SupportLinkStatus.claimed)  # claimed only: not counted
    return {"sso": sso.id, "excel": excel.id, "dark": dark.id, "gone": gone.id, "ent": ent.id}


def titles(r: Any) -> list[str]:
    assert r.status_code == 200, r.text
    return [n["title"] for n in r.json()["items"]]


def test_list_returns_a_page_and_hides_merged_needs(client: TestClient, backlog: dict[str, Any]) -> None:
    body = client.get("/needs").json()
    assert body["total"] == 3
    assert (body["page"], body["page_size"]) == (1, 20)
    assert "Old duplicate of SSO" not in [n["title"] for n in body["items"]]


def test_search_matches_need_text_and_member_requests(client: TestClient, backlog: dict[str, Any]) -> None:
    assert titles(client.get("/needs", params={"q": "excel"})) == ["Finance needs month-end data in Excel"]
    assert titles(client.get("/needs", params={"q": "OKTA"})) == ["IT admins need SSO before rollout"]


def test_filters_by_status_area_and_segment(client: TestClient, backlog: dict[str, Any]) -> None:
    assert titles(client.get("/needs", params={"status": "planned"})) == ["SMB users want a dark theme"]
    assert titles(client.get("/needs", params={"product_area": "reporting"})) == [
        "Finance needs month-end data in Excel"
    ]
    # segment: needs with a member request or confirmed support from an account in that segment
    assert sorted(titles(client.get("/needs", params={"segment": "smb"}))) == [
        "IT admins need SSO before rollout",
        "SMB users want a dark theme",
    ]


def test_sorts_by_priority_support_and_recency(client: TestClient, backlog: dict[str, Any]) -> None:
    assert titles(client.get("/needs", params={"sort": "priority"})) == [
        "IT admins need SSO before rollout",
        "Finance needs month-end data in Excel",
        "SMB users want a dark theme",  # computed: D from 3k ARR only
    ]
    by_support = client.get("/needs", params={"sort": "support"}).json()["items"]
    assert by_support[0]["title"] == "IT admins need SSO before rollout"
    assert by_support[0]["support_count"] == 3  # Ana, Ben (requests) + Cy (confirmed support)
    assert (
        titles(client.get("/needs", params={"sort": "recent"}))[0] == "Finance needs month-end data in Excel"
    )


def test_paginates(client: TestClient, backlog: dict[str, Any]) -> None:
    page2 = client.get("/needs", params={"sort": "priority", "page": 2, "page_size": 2}).json()
    assert (page2["total"], page2["page"], page2["page_size"]) == (3, 2, 2)
    assert [n["title"] for n in page2["items"]] == ["SMB users want a dark theme"]


@pytest.mark.parametrize(
    "params", [{"sort": "votes"}, {"page_size": 101}, {"page": 0}, {"status": "nope"}, {"segment": "giant"}]
)
def test_invalid_query_returns_422_in_our_error_shape(
    client: TestClient, backlog: dict[str, Any], params: dict[str, Any]
) -> None:
    r = client.get("/needs", params=params)
    assert r.status_code == 422, r.text
    assert_error(r.json(), "validation_error")


def test_detail_includes_requests_supports_and_accounts(client: TestClient, backlog: dict[str, Any]) -> None:
    r = client.get(f"/needs/{backlog['sso']}")
    assert r.status_code == 200, r.text
    need = r.json()
    assert need["title"] == "IT admins need SSO before rollout"
    assert sorted(req["title"] for req in need["requests"]) == ["Azure AD login", "Okta SSO please"]
    assert [(s["requester_name"], s["link_status"]) for s in need["supports"]] == [("Cy", "confirmed")]
    assert sorted(a["name"] for a in need["accounts"]) == ["Contoso", "Northwind", "Tiny Bakery"]
    assert {a["segment"] for a in need["accounts"]} == {"enterprise", "mid_market", "smb"}
    assert need["support_count"] == 3


def test_detail_lists_claimed_support_without_counting_it(
    client: TestClient, backlog: dict[str, Any]
) -> None:
    need = client.get(f"/needs/{backlog['dark']}").json()
    assert [(s["requester_name"], s["link_status"]) for s in need["supports"]] == [("Ana", "claimed")]
    assert need["support_count"] == 1
    assert need["claimed_support_count"] == 1
    assert [a["name"] for a in need["accounts"]] == ["Tiny Bakery"]


def test_unknown_need_returns_404_in_our_error_shape(client: TestClient, backlog: dict[str, Any]) -> None:
    r = client.get("/needs/9999")
    assert r.status_code == 404, r.text
    assert_error(r.json(), "not_found")


def test_claimed_support_does_not_qualify_for_a_segment(client: TestClient, backlog: dict[str, Any]) -> None:
    # Ana (enterprise) only claimed the dark theme need; Ana's confirmed footprint is the SSO request
    assert titles(client.get("/needs", params={"segment": "enterprise"})) == [
        "IT admins need SSO before rollout"
    ]


def test_list_and_detail_agree_on_counts(client: TestClient, backlog: dict[str, Any]) -> None:
    keys = ("support_count", "claimed_support_count", "request_count", "account_count")
    listed = {n["id"]: n for n in client.get("/needs").json()["items"]}
    for need_id, summary in listed.items():
        detail = client.get(f"/needs/{need_id}").json()
        assert {k: detail[k] for k in keys} == {k: summary[k] for k in keys}, need_id


def test_recent_sort_orders_by_newest_member_request(client: TestClient, backlog: dict[str, Any]) -> None:
    assert titles(client.get("/needs", params={"sort": "recent"})) == [
        "Finance needs month-end data in Excel",  # 2 days ago
        "SMB users want a dark theme",  # 10 days ago
        "IT admins need SSO before rollout",  # newest request 20 days ago
    ]
