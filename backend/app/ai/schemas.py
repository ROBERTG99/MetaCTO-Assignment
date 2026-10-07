"""What the model is allowed to return (CLAUDE.md rule 4). Validated with Pydantic before anything is stored."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

ProductArea = Literal[
    "security_admin",
    "sharing",
    "export",
    "data_sources",
    "alerts",
    "mobile",
    "performance",
    "onboarding",
    "collaboration",
    "localization",
    "ui",
    "embedded",
    "other",
]
Severity = Literal["blocker", "important", "nice_to_have", "unknown"]
Label = Literal["same_need", "related", "different"]


class Extraction(BaseModel):
    """The underlying need behind one request."""

    model_config = ConfigDict(extra="forbid")

    need_statement: str = Field(
        description="Problem plus persona, e.g. 'Finance needs month-end figures in Excel'"
    )
    problem: str
    persona: str = Field(
        description="Who has the problem, as a short snake_case role, e.g. it_admin, finance"
    )
    job_to_be_done: str
    proposed_solution: str
    product_area: ProductArea
    severity_signal: Severity
    evidence: list[str] = Field(description="Short verbatim quotes from the request that support the fields")
    confidence: float = Field(ge=0, le=1)
    rationale: str


class Judgment(BaseModel):
    model_config = ConfigDict(extra="forbid")

    candidate_id: str
    label: Label
    confidence: float = Field(ge=0, le=1)
    rationale: str
    quotes: list[str] = Field(description="Verbatim quotes from the request that support the label")


class Adjudication(BaseModel):
    """One judgment per candidate need: is the new request the same need?"""

    model_config = ConfigDict(extra="forbid")

    judgments: list[Judgment]


class CandidateNeed(BaseModel):
    """A need as the adjudicator sees it (inside <candidates>)."""

    id: str
    title: str
    problem: str
    persona: str | None
    product_area: str | None
    examples: list[str] = []


class FitRating(BaseModel):
    """How much solving this need advances one company goal."""

    model_config = ConfigDict(extra="forbid")

    goal: str = Field(description="The goal's key, exactly as given in <goals>")
    rating: Literal[0, 1, 2, 3] = Field(
        description="0 none, 1 indirect or minor, 2 clear, 3 directly and substantially"
    )
    rationale: str = Field(description="One sentence about the problem, not about who asked")
    quote: str = Field(
        description="A short passage copied exactly from one <request>; empty if none supports it"
    )


class StrategicFit(BaseModel):
    """One rating per goal, each goal exactly once."""

    model_config = ConfigDict(extra="forbid")

    ratings: list[FitRating]


class RequesterUpdate(BaseModel):
    """A personal update to one supporter, about what they asked for."""

    model_config = ConfigDict(extra="forbid")

    requester_id: int = Field(description="The supporter's id, exactly as given in <supporters>")
    body: str = Field(description="Two to four sentences; refers to what this person asked for")


class CsNote(BaseModel):
    """An internal note for customer success about one affected account."""

    model_config = ConfigDict(extra="forbid")

    account_id: int = Field(description="The account's id, exactly as given in <accounts>")
    body: str


class UpdateDrafts(BaseModel):
    """One personal update per supporter and one CS note per affected account. Drafts only: a PM approves."""

    model_config = ConfigDict(extra="forbid")

    requester_updates: list[RequesterUpdate]
    cs_notes: list[CsNote]


Relation = Literal["overlaps", "blocks", "depends_on"]


class RelatedFinding(BaseModel):
    """Another need this one overlaps with, blocks or depends on, with the request that shows it."""

    model_config = ConfigDict(extra="forbid")

    need_id: int = Field(description="The related need's id, as returned by the tools")
    relation: Relation = Field(
        description="overlaps: same users or problem space; blocks: this need must ship first; "
        "depends_on: this need needs the other one first"
    )
    rationale: str = Field(description="One sentence: why, in terms of the problem")
    request_id: int = Field(description="A request of the related need, as returned by get_need")
    quote: str = Field(description="A short passage copied exactly from that request")


class RelatedNeeds(BaseModel):
    """The overlap agent's final answer. Empty when nothing in the backlog is related."""

    model_config = ConfigDict(extra="forbid")

    related: list[RelatedFinding]


class EvidenceQuote(BaseModel):
    model_config = ConfigDict(extra="forbid")

    request_id: int = Field(description="A request id from <requests>")
    quote: str = Field(description="A short passage copied exactly from that request")


class ImpactClaim(BaseModel):
    """A business-impact statement. Figures are cited by fact key and rendered by code, never typed."""

    model_config = ConfigDict(extra="forbid")

    statement: str = Field(description="No figures in the text; cite them in fact_keys")
    fact_keys: list[str] = Field(description="Keys from <facts> whose values support the statement")


class BriefRelatedNeed(BaseModel):
    model_config = ConfigDict(extra="forbid")

    need_id: int = Field(description="An id from <related_needs>")
    relation: Relation
    why_it_matters: str


class BriefOption(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    description: str
    tradeoffs: str


class DecisionBrief(BaseModel):
    """A one-page decision brief for a PM. The decision stays human; this only frames it."""

    model_config = ConfigDict(extra="forbid")

    summary: str
    problem: str
    who_is_affected: str
    business_impact: list[ImpactClaim]
    evidence: list[EvidenceQuote]
    related_needs: list[BriefRelatedNeed]
    options: list[BriefOption]
    recommendation: str
    confidence: float = Field(ge=0, le=1)
    confidence_rationale: str
    risks: list[str]
    open_questions: list[str]
