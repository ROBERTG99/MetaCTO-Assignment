"""Contract: GET /needs?sort=priority with breakdowns, and GET /insights/quadrant (spec §8, ADR 0009).

Priority is computed when read: these tests seed raw data (accounts, requests, supports, goal ratings) and
check what the API computes from it, including that a config change alone re-ranks the backlog.
"""

from collections.abc import Iterator
from dataclasses import replace
from datetime import date, timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.engine import Engine

from app.ai.pipeline import Deps
from app.main import create_app
from app.models import NeedStatus, Segment, SupportLinkStatus
from tests.conftest import Factory

SOON = date.today() + timedelta(days=30)
LATER = date.today() + timedelta(days=200)
ALL_LOW = {"enterprise_readiness": 0, "retention": 1, "self_serve_growth": 0}
ALL_HIGH = {"enterprise_readiness": 3, "retention": 1, "self_serve_growth": 0}


@pytest.fixture
def backlog(make: Factory) -> dict[str, int]:
    big = [make.account(f"Big{i}", Segment.enterprise, arr=400_000, renewal_date=LATER) for i in range(5)]
    renewing = make.account("Renewing", Segment.mid_market, arr=60_000, renewal_date=SOON)
    tiny = make.account("Tiny", Segment.smb, arr=20_000, renewal_date=LATER)
    lead = make.account(
        "Lead", Segment.enterprise, arr=0, is_prospect=True, pipeline_value=300_000, renewal_date=None
    )

    popular = make.need("Team leads need KPIs sent to people without a login", product_area="sharing")
    for i, a in enumerate(big):
        make.request(
            make.requester(a, f"P{i}"), popular, "Email the weekly KPIs", severity_signal="important"
        )
    make.rating(popular, ALL_LOW, accounts=5)

    strategic = make.need("IT admins need SSO before rollout", product_area="security_admin")
    make.request(make.requester(tiny, "T"), strategic, "SAML please", severity_signal="nice_to_have")
    make.rating(strategic, ALL_HIGH)

    # counted once although it has a request and a confirmed support; the claim and the dispute don't count
    pending = make.need("Ops needs alerts when a metric drops", product_area="alerts")
    ren = make.requester(renewing, "R")
    make.request(ren, pending, "Alert me", severity_signal="blocker")
    make.support(pending, ren, SupportLinkStatus.confirmed, severity="important")
    make.support(pending, make.requester(lead, "L"), SupportLinkStatus.claimed, severity="blocker")
    make.support(pending, make.requester(big[0], "Q"), SupportLinkStatus.disputed, severity="blocker")
    pending.fit_status = "pending"
    make._save(pending)

    shipped = make.need("Dark mode", product_area="ui", status=NeedStatus.shipped)
    make.rating(shipped, ALL_HIGH)
    return {"popular": popular.id, "strategic": strategic.id, "pending": pending.id, "shipped": shipped.id}  # type: ignore[dict-item]


def by_id(r: Any) -> dict[int, dict[str, Any]]:
    assert r.status_code == 200, r.text
    return {n["id"]: n for n in r.json()["items"]}


def test_every_need_carries_its_priority_breakdown(client: TestClient, backlog: dict[str, int]) -> None:
    needs = by_id(client.get("/needs", params={"sort": "priority"}))
    p = needs[backlog["popular"]]
    b = p["breakdown"]
    # R = 5 x 400k = 2M -> D = log10(2001) / log10(5001) = 0.892456; U = 0.6 x 0.5 = 0.3; S = 0.35 x 1/3
    assert b["demand"]["value"] == pytest.approx(0.892456, abs=1e-6)
    assert (b["demand"]["accounts"], b["demand"]["customers"], b["demand"]["prospects"]) == (5, 5, 0)
    assert (b["urgency"]["value"], b["urgency"]["max_severity"], b["urgency"]["renewal_soon"]) == (
        pytest.approx(0.3),
        "important",
        False,
    )
    assert b["strategic"]["value"] == pytest.approx(0.35 / 3)
    assert p["priority_score"] == pytest.approx(sum(b["contributions"].values()))
    assert p["priority_score"] == pytest.approx(100 * (0.4 * 0.892456 + 0.4 * 0.35 / 3 + 0.2 * 0.3), abs=1e-3)
    assert (b["quadrant"], b["owner"]) == ("popular_off_strategy", "reporting")


def test_strategic_ratings_show_their_source_rationale_and_weight(
    client: TestClient, backlog: dict[str, int]
) -> None:
    s = client.get(f"/needs/{backlog['strategic']}").json()["breakdown"]["strategic"]
    assert (s["status"], s["model"], s["prompt_version"]) == ("rated", "claude-haiku-4-5", "strategic_fit_v1")
    assert s["value"] == pytest.approx(0.4 + 0.35 / 3)
    goals = {g["goal"]: g for g in s["goals"]}
    assert set(goals) == {"enterprise_readiness", "retention", "self_serve_growth"}
    er = goals["enterprise_readiness"]
    assert (er["rating"], er["weight"], er["title"]) == (3, 0.4, "Enterprise readiness")
    assert er["rationale"] == "enterprise_readiness rated 3"


def test_only_confirmed_support_counts_and_each_account_counts_once(
    client: TestClient, backlog: dict[str, int]
) -> None:
    b = client.get(f"/needs/{backlog['pending']}").json()["breakdown"]
    assert b["demand"]["accounts"] == 1  # the claim (Lead) and the dispute (Big0) are not counted
    assert b["demand"]["revenue"] == pytest.approx(60_000 * 0.9)
    assert (b["urgency"]["max_severity"], b["urgency"]["renewal_soon"]) == ("blocker", True)
    assert b["urgency"]["renewing_accounts"] == ["Renewing"]


def test_an_unrated_need_says_so_and_renormalises(client: TestClient, backlog: dict[str, int]) -> None:
    n = client.get(f"/needs/{backlog['pending']}").json()
    b = n["breakdown"]
    assert (b["strategic"]["status"], b["strategic"]["value"], b["quadrant"]) == ("pending", None, None)
    assert set(b["weights"]) == {"demand", "urgency"}
    assert n["priority_score"] == pytest.approx(sum(b["contributions"].values()))


def test_sort_by_priority_follows_the_computed_score(client: TestClient, backlog: dict[str, int]) -> None:
    items = client.get("/needs", params={"sort": "priority"}).json()["items"]
    scores = [n["priority_score"] for n in items]
    assert scores == sorted(scores, reverse=True)
    # pending 64.7 (unrated: D and U renormalised), popular 46.3, strategic 36.4, shipped 20.7 (S only)
    assert [n["id"] for n in items] == [backlog[k] for k in ("pending", "popular", "strategic", "shipped")]


@pytest.fixture
def client_with(engine: Engine, deps: Deps) -> Iterator[Any]:
    clients: list[TestClient] = []

    def make_client(**weights: Any) -> TestClient:
        c = TestClient(create_app(engine, deps=replace(deps, priorities=replace(deps.priorities, **weights)),
                                  start_worker=False))  # fmt: skip
        clients.append(c.__enter__())
        return c

    yield make_client
    for c in clients:
        c.__exit__(None, None, None)


def test_a_weight_change_in_config_alone_re_ranks_the_backlog(
    client_with: Any, backlog: dict[str, int]
) -> None:
    def top(c: TestClient) -> int:
        items = c.get("/needs", params={"sort": "priority", "status": "open"}).json()["items"]
        rated = [n for n in items if n["breakdown"]["strategic"]["value"] is not None]
        return int(rated[0]["id"])

    assert top(client_with()) == backlog["popular"]
    assert top(client_with(w_demand=0.2, w_strategic=0.7, w_urgency=0.1)) == backlog["strategic"]


def test_quadrant_view_groups_undecided_needs(client: TestClient, backlog: dict[str, int]) -> None:
    r = client.get("/insights/quadrant")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["cutoffs"] == {"popular": 0.6, "strategic": 0.5}
    ids = {k: [n["id"] for n in v] for k, v in body["quadrants"].items()}
    assert ids == {
        "clear_win": [],
        "strategic_bet": [backlog["strategic"]],
        "popular_off_strategy": [backlog["popular"]],
        "park": [],
    }
    assert [n["id"] for n in body["not_rated"]] == [backlog["pending"]]  # shipped needs are decided: left out
    first = body["quadrants"]["strategic_bet"][0]
    assert (first["owner"], first["account_count"]) == ("platform", 1)
    assert first["strategic"] == pytest.approx(0.4 + 0.35 / 3)
