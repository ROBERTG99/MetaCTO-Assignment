"""API contract types (request bodies and responses). Tables live in models.py."""

from datetime import date, datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from app.models import (
    NeedStatus,
    RequestSource,
    RequestStatus,
    Segment,
    Severity,
    SupportLinkStatus,
)

Title = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
Description = Annotated[str, StringConstraints(max_length=5000)]
Why = Annotated[str, StringConstraints(strip_whitespace=True, max_length=2000)]
NeedSort = Literal["priority", "support", "recent"]
MAX_ID = 2**63 - 1  # SQLite INTEGER
Id = Annotated[int, Field(ge=1, le=MAX_ID)]


class ErrorDetail(BaseModel):
    field: str
    issue: str


class ErrorInfo(BaseModel):
    code: str
    message: str
    details: list[ErrorDetail] = []


class ErrorResponse(BaseModel):
    error: ErrorInfo


class RequestCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    requester_id: Id
    account_id: Id | None = Field(
        None, description="The customer this is for. Required when staff submit for support, sales or cs."
    )
    title: Title
    description: Description = ""
    source: RequestSource


class RequestOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    requester_id: int
    account_id: int | None
    source: RequestSource
    title: str
    description: str
    status: RequestStatus
    need_id: int | None
    problem: str | None
    persona: str | None
    job_to_be_done: str | None
    proposed_solution: str | None
    product_area: str | None
    created_at: datetime


class SupportCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    requester_id: Id
    why_it_matters: Why | None = Field(None, description="Omit on a repeat to keep the stored reason")
    severity: Severity


class SupportOut(BaseModel):
    id: int
    need_id: int
    requester_id: int
    requester_name: str
    account_name: str | None
    why_it_matters: str
    severity: Severity
    link_status: SupportLinkStatus
    created_at: datetime


class AccountOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    segment: Segment
    arr: int
    is_prospect: bool
    pipeline_value: int | None
    renewal_date: date | None


class NeedRequestOut(BaseModel):
    id: int
    title: str
    description: str
    source: RequestSource
    status: RequestStatus
    requester_name: str
    account_name: str | None
    created_at: datetime


class NeedSummary(BaseModel):
    id: int
    title: str
    problem: str
    persona: str | None
    product_area: str | None
    status: NeedStatus
    priority_score: float | None
    support_count: int = Field(
        description="Distinct requesters with a member request or a confirmed support. Staff filing for several "
        "customers count once; account_count shows the customers."
    )
    claimed_support_count: int = Field(
        description="Supports still waiting for the intake workflow to confirm them"
    )
    request_count: int
    account_count: int
    last_request_at: datetime | None
    created_at: datetime


class NeedPage(BaseModel):
    items: list[NeedSummary]
    total: int
    page: int
    page_size: int


class NeedDetail(NeedSummary):
    job_to_be_done: str | None
    merged_into_id: int | None
    demand: float | None
    urgency: float | None
    strategic_fit: float | None
    requests: list[NeedRequestOut]
    supports: list[SupportOut]
    accounts: list[AccountOut]


class NeedRef(BaseModel):
    id: int
    title: str
    problem: str
    persona: str | None
    product_area: str | None


class TriageRequest(BaseModel):
    id: int
    title: str
    description: str
    need_statement: str | None
    persona: str | None


class TriageSupport(BaseModel):
    id: int
    why_it_matters: str
    severity: Severity
    claimed_need: NeedRef | None
    reason: str | None


class TriageItem(BaseModel):
    id: int
    kind: Literal["suggestion", "claim", "audit"]
    routing_score: float | None
    label: str | None
    model_confidence: float | None
    rationale: str | None
    quotes: list[str]
    created_at: datetime
    need: NeedRef | None = Field(
        description="Suggestion and audit: the need of the link. Claim: the claimed need"
    )
    alternative_need: NeedRef | None = Field(description="Claim only: the need the model would pick instead")
    request: TriageRequest | None
    support: TriageSupport | None


class FailedRequest(BaseModel):
    id: int
    title: str
    reason: str | None
    attempts: int


class TriageList(BaseModel):
    items: list[TriageItem]
    needs_review: list[FailedRequest]


class DecisionResult(BaseModel):
    id: int
    kind: Literal["suggestion", "claim", "audit"]
    state: str
    audit_verdict: str | None
    need_id: int | None


class UnlinkResult(BaseModel):
    request_id: int
    need_id: int
    title: str


class SimilarNeed(BaseModel):
    need_id: int
    title: str
    problem: str
    persona: str | None
    product_area: str | None
    status: NeedStatus
    score: float
