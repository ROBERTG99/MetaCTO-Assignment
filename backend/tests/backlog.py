"""A small processed backlog for AI tests: two needs, one member each, indexed with the fake embedder."""

from dataclasses import dataclass
from typing import Any, cast

from sqlmodel import Session

from app.ai.pipeline import Deps
from app.ai.schemas import Adjudication, Extraction, Judgment, Label
from app.models import Need, Request, Requester, RequestStatus, Segment
from tests.conftest import Factory

SSO_TEXT = ("Okta SSO please", "We need SAML single sign-on with Okta for every employee")


@dataclass
class Backlog:
    sso: Need
    dark: Need
    it: Requester
    smb: Requester


def build(db: Session, make: Factory, deps: Deps) -> Backlog:
    ent = make.account("Northwind", Segment.enterprise, arr=400_000)
    smb_acct = make.account("Tiny Bakery", Segment.smb, arr=3_000)
    it, smb = make.requester(ent, "Priya", "IT Director"), make.requester(smb_acct, "Rosa", "Owner")
    sso = make.need(
        "IT admins need single sign-on with Okta",
        persona="it_admin",
        product_area="security_admin",
        created_by="ai",
    )
    dark = make.need(
        "Users want a dark theme at night", persona="end_user", product_area="ui", created_by="ai"
    )
    make.request(it, sso, SSO_TEXT[0], description=SSO_TEXT[1], status=RequestStatus.processed)
    make.request(
        smb,
        dark,
        "dark mode please",
        description="the white screen at night hurts",
        status=RequestStatus.processed,
    )
    deps.search.rebuild(db)
    return Backlog(sso, dark, it, smb)


def new_request(make: Factory, requester: Requester, title: str, description: str) -> Request:
    return make.request(requester, None, title, description=description, status=RequestStatus.pending)


def extraction(
    persona: str = "it_admin", area: Any = "security_admin", statement: str = "IT admins need SSO"
) -> Extraction:
    return Extraction(
        need_statement=statement, problem="sign in once", persona=persona, job_to_be_done="roll out",
        proposed_solution="SAML", product_area=area, severity_signal="blocker", evidence=[], confidence=0.9,
        rationale="r",
    )  # fmt: skip


def judge(**labels: str) -> Adjudication:
    """judge(**{"3": "same_need"}) -> one judgment per candidate id given."""
    return Adjudication(
        judgments=[
            Judgment(candidate_id=cid, label=cast(Label, lab), confidence=0.9, rationale="r", quotes=[])
            for cid, lab in labels.items()
        ]
    )
