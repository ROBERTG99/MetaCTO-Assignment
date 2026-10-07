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
