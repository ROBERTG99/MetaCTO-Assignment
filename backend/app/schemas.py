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


class DemandOut(BaseModel):
    value: float = Field(description="D, 0-1: log-scaled weighted revenue over unique accounts")
    revenue: float = Field(
        description="R: ARR x segment weight (customers) + p_win x pipeline x segment weight"
    )
    customer_revenue: float
    prospect_revenue: float
    accounts: int
    customers: int
    prospects: int
    gaps: list[str] = Field(description="Accounts counted with no ARR or pipeline value on record")


class UrgencyOut(BaseModel):
    value: float = Field(description="U, 0-1: highest severity, plus a renewal within the window")
    max_severity: str | None
    severity_score: float
    renewal_soon: bool
    renewing_accounts: list[str]


class GoalRatingOut(BaseModel):
    goal: str
    title: str
    weight: float = Field(description="From config/priorities.yaml now, not when the rating was made")
    rating: int | None = Field(description="0-3, rated by the model")
    contribution: float = Field(description="weight x rating / 3")
    rationale: str | None
    quote: str | None = Field(description="Verified verbatim in the need's requests")
    quote_dropped: bool = Field(
        description="The model quoted text that isn't in the requests; it was dropped"
    )


class StrategicOut(BaseModel):
    value: float | None = Field(description="S, 0-1; null until every configured goal is rated")
    status: Literal["rated", "stale", "pending", "failed", "not_rated"] = Field(
        description="stale: rated against goals that have changed since; re-rated on the next support change"
    )
    model: str | None
    prompt_version: str | None
    ai_run_id: int | None
    rated_at_accounts: int | None
    rerating_queued: bool
    error: str | None
    goals: list[GoalRatingOut]


Quadrant = Literal["clear_win", "strategic_bet", "popular_off_strategy", "park"]


class PriorityBreakdown(BaseModel):
    priority: float = Field(description="0-100, the sum of contributions")
    contributions: dict[str, float] = Field(description="Points per component: 100 x weight x value")
    weights: dict[str, float] = Field(description="Weights used; renormalised while strategic is unrated")
    demand: DemandOut
    urgency: UrgencyOut
    strategic: StrategicOut
    quadrant: Quadrant | None = Field(description="Popular is demand, strategic is S; null while unrated")
    owner: str = Field(description="The PM team that owns the product area")


class NeedSummary(BaseModel):
    id: int
    title: str
    problem: str
    persona: str | None
    product_area: str | None
    status: NeedStatus
    priority_score: float = Field(description="0-100, computed when read from current data and config")
    breakdown: PriorityBreakdown
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


class QuadrantNeed(BaseModel):
    id: int
    title: str
    product_area: str | None
    owner: str
    priority: float
    demand: float
    strategic: float | None
    account_count: int
    quadrant: Quadrant | None


class QuadrantView(BaseModel):
    cutoffs: dict[str, float] = Field(description="Inclusive cut-offs from config/priorities.yaml")
    quadrants: dict[str, list[QuadrantNeed]] = Field(
        description="clear_win, strategic_bet, popular_off_strategy, park; highest priority first"
    )
    not_rated: list[QuadrantNeed] = Field(
        description="Strategic fit not rated yet (pending, failed or offline)"
    )
