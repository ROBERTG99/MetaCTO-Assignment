"""Enrichment: demand, urgency and priority from account data (spec §8), hand-computed."""

from datetime import date

import pytest
from sqlmodel import Session

from app.models import RequestStatus, Segment, SupportLinkStatus
from app.scoring import PrioritiesConfig, refresh_need
from tests.conftest import Factory

TODAY = date(2026, 10, 7)


def test_demand_urgency_and_priority(db: Session, make: Factory) -> None:
    a = make.account(
        "A", Segment.enterprise, arr=100_000, renewal_date=date(2026, 11, 6)
    )  # renews in 30 days
    b = make.account(
        "B", Segment.enterprise, arr=0, is_prospect=True, pipeline_value=200_000, renewal_date=None
    )
    c = make.account("C", Segment.mid_market, arr=60_000, renewal_date=date(2027, 4, 25))  # 200 days
    d = make.account("D", Segment.enterprise, arr=1_000_000)
    need = make.need("Finance needs month-end figures in Excel")
    make.request(make.requester(a, "Ann"), need, "x", status=RequestStatus.processed)
    make.request(make.requester(None, "Ryan"), need, "y", account_id=b.id, status=RequestStatus.processed)
    make.support(need, make.requester(c, "Cy"), SupportLinkStatus.confirmed, severity="blocker")
    make.support(need, make.requester(d, "Dee"), SupportLinkStatus.claimed, severity="blocker")  # not counted
    out = refresh_need(db, need.id, PrioritiesConfig(), today=TODAY)  # type: ignore[arg-type]
    # R = 100k (A) + 0.2 x 200k (B) + 60k (C) = 200k; D = log10(1 + 200) / log10(1 + 5000) = 0.622643
    assert out.demand == pytest.approx(0.622643, abs=1e-5)
    # U = 0.6 x 1.0 (blocker) + 0.4 x 100k / (100k + 60k) = 0.6 + 0.25 = 0.85
    assert out.urgency == pytest.approx(0.85)
    # strategic not rated: 100 x (0.40 x 0.622643 + 0.25 x 0.85) / (0.40 + 0.25) = 71.0088
    assert out.priority_score == pytest.approx(71.0088, abs=1e-3)


def test_a_need_with_no_supporters_scores_zero(db: Session, make: Factory) -> None:
    need = make.need("Nobody yet")
    out = refresh_need(db, need.id, PrioritiesConfig(), today=TODAY)  # type: ignore[arg-type]
    assert (out.demand, out.urgency, out.priority_score) == (0.0, 0.0, 0.0)
