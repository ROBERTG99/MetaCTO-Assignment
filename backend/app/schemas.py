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


class AISource(BaseModel):
    """Which model (or "offline-baseline") produced an AI value, with which prompt, in which ai_runs row."""

    model: str | None
    prompt_version: str | None
    ai_run_id: int | None


class RequestAnalysis(BaseModel):
    """The extraction step's reading of one request (AI-generated: show source, confidence, rationale)."""

    need_statement: str | None
    problem: str | None
    persona: str | None
    job_to_be_done: str | None
    proposed_solution: str | None
    product_area: str | None
    severity_signal: str | None
    confidence: float | None
    rationale: str | None
    source: AISource | None


class LinkInfo(BaseModel):
    """How the request joined this need: by the intake workflow (auto), a PM, or as the need's first request."""

    actor: str
    at: datetime
    routing_score: float | None
    label: str | None
    rationale: str | None
    source: AISource | None


class NeedRequestOut(BaseModel):
    id: int
    title: str
    description: str
    source: RequestSource
    status: RequestStatus
    requester_name: str
    account_name: str | None
    created_at: datetime
    analysis: RequestAnalysis | None = None
    link: LinkInfo | None = None


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


class NeedOrigin(BaseModel):
    created_by: str = Field(description="ai | pm | seed")
    source: AISource | None
    rationale: str | None
    created_at: datetime


class Evidence(BaseModel):
    quote: str = Field(description="Verbatim from a request, verified in code")
    kind: Literal["link", "strategic_fit"]
    request_id: int | None
    goal: str | None


class AuditEvent(BaseModel):
    at: datetime
    kind: Literal["link", "unlink", "status", "decision", "ai_run"]
    actor: str = Field(description="auto, pm (or the PM's name), requester_claim, or the model for ai_run")
    summary: str
    request_id: int | None = None
    model: str | None = None


class UpdateOut(BaseModel):
    id: int
    kind: str = Field(
        description="requester_update (to requester_id) or cs_note (for an account; PM view only)"
    )
    requester_id: int | None
    body: str
    requester_name: str | None
    approved_at: datetime | None


class NeedDetail(NeedSummary):
    job_to_be_done: str | None
    merged_into_id: int | None
    requests: list[NeedRequestOut]
    supports: list[SupportOut]
    accounts: list[AccountOut]
    origin: NeedOrigin
    evidence: list[Evidence]
    updates: list[UpdateOut] = Field(
        description="Approved updates sent to supporters (drafts are never shown)"
    )
    audit_trail: list[AuditEvent] = Field(
        description="Links, unlinks, status changes, decisions and AI runs, newest first"
    )


SettableStatus = Literal["open", "planned", "in_progress", "shipped", "declined"]


class NeedStatusUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: SettableStatus = Field(description="A human product decision; merged is set only by merging")
    by: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]


class NeedRef(BaseModel):
    id: int
    title: str
    problem: str
    persona: str | None
    product_area: str | None


class RoutingParts(BaseModel):
    """How a routing score was reached (spec §8, ADR 0003). Points are on the score's own scale (0-1).

    llm: label points (same_need or nothing) + similarity points + field-agreement points.
    baseline (offline): the score is the embedding similarity itself; there is no label or field part.
    """

    mode: Literal["llm", "baseline"]
    score: float | None
    label: str | None
    similarity: float | None = Field(description="Best cosine similarity; null if it couldn't be recovered")
    area_match: bool | None
    persona_match: bool | None
    label_points: float
    similarity_points: float
    field_points: float
    auto_threshold: float | None
    suggest_threshold: float | None


class TriageRequest(BaseModel):
    id: int
    title: str
    description: str
    need_statement: str | None
    persona: str | None
    problem: str | None = None
    product_area: str | None = None
    requester_name: str | None = None
    account_name: str | None = None
    created_at: datetime | None = None


class TriageSupport(BaseModel):
    id: int
    why_it_matters: str
    severity: Severity
    claimed_need: NeedRef | None
    reason: str | None


class TriageItem(BaseModel):
    id: int
    kind: Literal["suggestion", "claim", "audit", "auto_link"]
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
    source: AISource | None = Field(None, description="The run behind this decision")
    routing: RoutingParts | None = None


class FailedRequest(BaseModel):
    id: int
    title: str
    reason: str | None
    attempts: int


class TriageList(BaseModel):
    items: list[TriageItem] = Field(description="Waiting for a decision: suggestions, claims, audit sample")
    auto_linked: list[TriageItem] = Field(
        description="Auto-links still in place, newest first (at most 50): each can be undone (CLAUDE.md rule 2)"
    )
    auto_linked_total: int = Field(description="All auto-links still in place")
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


class RequesterOut(BaseModel):
    id: int
    name: str
    role: str
    account_id: int | None
    account_name: str | None = Field(description="None for Brightboard staff")
    segment: Segment | None


class MyRequest(BaseModel):
    id: int
    title: str
    description: str
    status: RequestStatus
    needs_review_reason: str | None
    created_at: datetime
    processed_at: datetime | None
    need: NeedRef | None


class RateOut(BaseModel):
    k: int
    n: int
    value: float | None
    low: float = Field(description="Wilson 95% lower bound")
    high: float = Field(description="Wilson 95% upper bound")


class RunStats(BaseModel):
    step: str
    model: str
    prompt_version: str
    calls: int
    ok: int
    failure_rate: float
    cost_usd: float
    cost_per_call: float
    p50_ms: int
    p95_ms: int


class OpsTotals(BaseModel):
    calls: int
    cost_usd: float
    processed_requests: int
    cost_per_request: float | None


class FalseMergeOut(BaseModel):
    audited: RateOut = Field(description="M4: audited auto-links marked false_merge / audited auto-links")
    target: float
    within_target: bool | None = Field(description="Upper bound at or under target; null with no audits")
    auto_links: int
    undone: int
    undo_rate: float | None = Field(
        description="Undone auto-links / auto-links: a lower bound on false merges"
    )


class M1Out(BaseModel):
    processed: int = Field(description="Requests the intake workflow finished: processed or needs review")
    untouched: int = Field(description="No PM link or decision, no open suggestion, not failed")
    value: float | None = Field(description="Share of processed requests no PM had to touch")
    pm_minutes_per_100: float | None = Field(description="Touched share x 100 requests x 2 minutes (spec A6)")


class M2Out(BaseModel):
    claims: int
    new_requests: int
    deflection: float | None = Field(description="Claims at the door / (claims + new requests)")
    new_need_requests: int
    relinked_by_pm: int
    leakage: float | None = Field(
        description="Requests routed to a new need that a PM later linked to an existing one"
    )
    note: str


class M3Out(BaseModel):
    value: float | None
    note: str


class OpsMetrics(BaseModel):
    runs: list[RunStats]
    totals: OpsTotals
    acceptance: RateOut = Field(description="PM-accepted suggestions / decided suggestions")
    needs_review: RateOut = Field(description="Guardrail: finished requests that failed to needs_review")
    false_merge: FalseMergeOut
    m1: M1Out
    m2: M2Out
    m3: M3Out
