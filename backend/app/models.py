"""Tables. Nothing an AI produced is ever deleted: suggestions and support links change state instead."""

from datetime import UTC, date, datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import JSON, Column, UniqueConstraint
from sqlmodel import Field, SQLModel


def utcnow() -> datetime:
    return datetime.now(UTC)


class Segment(StrEnum):
    enterprise = "enterprise"
    mid_market = "mid_market"
    smb = "smb"


class RequestSource(StrEnum):
    portal = "portal"
    support = "support"
    sales = "sales"
    cs = "cs"
    internal = "internal"


class RequestStatus(StrEnum):
    pending = "pending"
    processing = "processing"
    processed = "processed"
    needs_review = "needs_review"


class Severity(StrEnum):
    nice_to_have = "nice_to_have"
    important = "important"
    blocker = "blocker"


class NeedStatus(StrEnum):
    open = "open"
    planned = "planned"
    in_progress = "in_progress"
    shipped = "shipped"
    declined = "declined"
    merged = "merged"


class SupportLinkStatus(StrEnum):
    claimed = (
        "claimed"  # the requester said "this is my need"; not counted until the intake workflow confirms it
    )
    confirmed = "confirmed"
    disputed = "disputed"
    rejected = "rejected"


class SuggestionKind(StrEnum):
    duplicate = "duplicate"
    related = "related"
    new_need = "new_need"


class SuggestionState(StrEnum):
    proposed = "proposed"
    applied = "applied"  # auto-linked by policy
    accepted = "accepted"
    rejected = "rejected"
    undone = "undone"


class Account(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    name: str = Field(index=True)
    segment: Segment
    arr: int = 0  # USD per year; 0 for prospects
    renewal_date: date | None = None
    is_prospect: bool = False
    pipeline_value: int | None = None  # USD; prospects only


class Requester(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    name: str
    role: str
    account_id: int | None = Field(default=None, foreign_key="account.id")  # None: Brightboard staff


class Need(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    title: str
    problem: str = ""
    persona: str | None = None
    job_to_be_done: str | None = None
    product_area: str | None = Field(default=None, index=True)
    status: NeedStatus = Field(default=NeedStatus.open, index=True)
    merged_into_id: int | None = Field(default=None, foreign_key="need.id")
    created_by: str = "ai"  # ai | pm | seed
    # Priority isn't stored: it is computed when read, from current data and config (ADR 0009).
    # Strategic fit is a job on the need row (ADR 0007 pattern): pending -> rated, or failed with a reason.
    fit_status: str | None = Field(default=None, index=True)  # pending | rated | failed
    fit_accounts: int | None = None  # supporting accounts when the latest rating was queued
    fit_attempts: int = 0
    fit_started_at: datetime | None = None
    fit_error: str | None = None
    fit_goals_digest: str | None = (
        None  # the goals the ratings in use were made against (scoring.goals_digest)
    )
    fit_run_id: int | None = None  # airun.id of the ratings in use; no FK: AIRun.need_id already points here
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)


class Request(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    requester_id: int = Field(foreign_key="requester.id", index=True)
    account_id: int | None = Field(default=None, foreign_key="account.id")
    source: RequestSource
    title: str
    description: str = ""
    status: RequestStatus = Field(default=RequestStatus.pending, index=True)
    # Queue bookkeeping (ADR 0007: the request row is the job)
    attempts: int = 0
    last_error: str | None = None
    claimed_at: datetime | None = None
    needs_review_reason: str | None = None
    # Filled by the intake workflow; null until then
    redacted_text: str | None = None
    problem: str | None = None
    persona: str | None = None
    job_to_be_done: str | None = None
    proposed_solution: str | None = None
    product_area: str | None = None
    severity_signal: str | None = None
    extraction_confidence: float | None = None
    extraction_rationale: str | None = None
    need_statement: str | None = None  # problem plus persona, from the extraction
    need_id: int | None = Field(default=None, foreign_key="need.id", index=True)
    created_at: datetime = Field(default_factory=utcnow, index=True)
    processed_at: datetime | None = None


class Support(SQLModel, table=True):
    __table_args__ = (UniqueConstraint("need_id", "requester_id"),)

    id: int | None = Field(default=None, primary_key=True)
    need_id: int = Field(foreign_key="need.id", index=True)
    requester_id: int = Field(foreign_key="requester.id")
    why_it_matters: str = ""
    severity: Severity = Severity.important
    link_status: SupportLinkStatus = SupportLinkStatus.claimed
    # The intake workflow checks a claim like a request (ADR 0007); a terminal failure disputes it
    check_attempts: int = 0
    check_started_at: datetime | None = None
    check_error: str | None = None
    review_reason: str | None = None
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)


class LinkAction(StrEnum):
    link = "link"
    unlink = "unlink"


class LinkActor(StrEnum):
    auto = "auto"  # routing policy above T_auto
    pm = "pm"
    requester_claim = "requester_claim"


class LinkEvent(SQLModel, table=True):
    """Append-only history of every link and unlink between a request or support and a need.

    Request.need_id and Support.link_status hold the current state; this table holds how it got there,
    which is what undo, the audit sample and the AI audit trail read. Rows are never updated or deleted.
    """

    id: int | None = Field(default=None, primary_key=True)
    action: LinkAction
    actor: LinkActor
    actor_id: str | None = None  # requester or PM id; None for auto
    need_id: int = Field(foreign_key="need.id", index=True)
    request_id: int | None = Field(default=None, foreign_key="request.id", index=True)
    support_id: int | None = Field(default=None, foreign_key="support.id", index=True)
    suggestion_id: int | None = Field(default=None, foreign_key="aisuggestion.id")
    routing_score: float | None = None
    reason: str | None = None  # e.g. "undo", "audit: false_merge", "claim disputed"
    created_at: datetime = Field(default_factory=utcnow, index=True)


class AISuggestion(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    request_id: int | None = Field(default=None, foreign_key="request.id", index=True)
    support_id: int | None = Field(default=None, foreign_key="support.id")  # set when checking a claim
    need_id: int | None = Field(default=None, foreign_key="need.id")
    kind: SuggestionKind
    label: str | None = None  # same_need | related | different
    routing_score: float | None = None
    model_confidence: float | None = None
    rationale: str | None = None
    quotes: list[str] = Field(default_factory=list, sa_column=Column(JSON))
    state: SuggestionState = SuggestionState.proposed
    audit_sample: bool = False
    audit_verdict: str | None = None  # correct | false_merge
    decided_by: str | None = None
    decided_at: datetime | None = None
    ai_run_id: int | None = Field(default=None, foreign_key="airun.id")
    created_at: datetime = Field(default_factory=utcnow)


class AIRun(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    step: str
    model: str
    prompt_version: str
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0
    latency_ms: int = 0
    outcome: str  # ok | refusal | max_tokens | validation_error | provider_error | timeout
    error: str | None = None
    request_id: int | None = Field(default=None, foreign_key="request.id")
    need_id: int | None = Field(default=None, foreign_key="need.id")
    created_at: datetime = Field(default_factory=utcnow)


class GoalRating(SQLModel, table=True):
    """One goal's 0-3 rating from one strategic-fit run. Rows are never updated: a re-rating adds a run, and
    Need.fit_run_id points at the one in use. S is computed from these with the current goal weights."""

    id: int | None = Field(default=None, primary_key=True)
    need_id: int = Field(foreign_key="need.id", index=True)
    ai_run_id: int = Field(foreign_key="airun.id", index=True)
    goal: str
    rating: int
    rationale: str
    quote: str | None = None  # kept only if found verbatim in the requests the model was given
    quote_dropped: bool = False  # the model quoted something that isn't in them
    created_at: datetime = Field(default_factory=utcnow)


class StakeholderUpdate(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    need_id: int = Field(foreign_key="need.id", index=True)
    kind: str  # requester_update | cs_note
    requester_id: int | None = Field(default=None, foreign_key="requester.id")
    account_id: int | None = Field(default=None, foreign_key="account.id")
    body: str
    flagged_commitments: list[Any] = Field(default_factory=list, sa_column=Column(JSON))
    status: str = "draft"  # draft | approved | discarded
    approved_by: str | None = None
    approved_at: datetime | None = None
    ai_run_id: int | None = Field(default=None, foreign_key="airun.id")
    created_at: datetime = Field(default_factory=utcnow)
