"""Load the Brightboard seed into a fresh database: `make seed` (with recorded AI output) or `make seed-raw`.

Raw data: accounts, requesters and requests, all pending. With the snapshot (the default for `make seed`),
the recorded Haiku 4.5 output in snapshot.json is applied on top: extractions, routing decisions, needs,
links, suggestions and AI runs, validated with the same schemas as live output and checked against the
locked config. It comes from the cached eval dev replay (evals/snapshot.py), not from live calls.
ground_truth.json is for tests and evals and is never loaded.
"""

import json
import sys
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field, ValidationError, model_validator
from sqlalchemy.engine import Engine
from sqlmodel import Session, SQLModel

from app.ai.pipeline import verify_quotes
from app.ai.policy import RoutingConfig, in_audit_sample, load_routing
from app.ai.redact import redact
from app.ai.schemas import Extraction
from app.db import create_tables, get_engine
from app.models import (
    Account,
    AIRun,
    AISuggestion,
    LinkAction,
    LinkActor,
    LinkEvent,
    Need,
    Request,
    Requester,
    RequestSource,
    RequestStatus,
    Segment,
    SuggestionKind,
    SuggestionState,
)
from app.scoring import load_priorities, refresh_need

SEED_DIR = Path(__file__).resolve().parent
SNAPSHOT = SEED_DIR / "snapshot.json"
CONFIG = SEED_DIR.parents[1] / "config"
START = datetime(2026, 7, 1, 9, 0, tzinfo=UTC)


def _read(name: str) -> Any:
    return json.loads((SEED_DIR / name).read_text(encoding="utf-8"))


def load_seed(engine: Engine, snapshot: bool = False) -> dict[str, int]:
    """Drop and recreate every table, then insert the seed. Returns the row counts.

    With snapshot=True, the recorded Haiku output in snapshot.json is applied on top (see apply_snapshot).
    """
    import app.models  # noqa: F401  (registers the tables)

    SQLModel.metadata.drop_all(engine)
    create_tables(engine)
    with Session(engine) as session:
        accounts: dict[str, Account] = {}
        for a in _read("accounts.json"):
            accounts[a["ref"]] = Account(
                name=a["name"],
                segment=Segment(a["segment"]),
                arr=a["arr"],
                renewal_date=date.fromisoformat(a["renewal_date"]) if a.get("renewal_date") else None,
                is_prospect=a.get("is_prospect", False),
                pipeline_value=a.get("pipeline_value"),
            )
        session.add_all(accounts.values())
        session.flush()
        people: dict[str, Requester] = {}
        for p in _read("requesters.json"):
            account = accounts[p["account"]] if p["account"] else None
            people[p["ref"]] = Requester(
                name=p["name"], role=p["role"], account_id=account.id if account else None
            )
        session.add_all(people.values())
        session.flush()
        requests = []
        for r in _read("requests.json"):
            requester = people[r["requester"]]
            assert requester.id is not None
            account_id = accounts[r["account"]].id if r["account"] else requester.account_id
            requests.append(
                Request(
                    requester_id=requester.id,
                    account_id=account_id,
                    source=RequestSource(r["source"]),
                    title=r["title"],
                    description=r["description"],
                    status=RequestStatus.pending,
                    created_at=START + timedelta(days=r["day"], minutes=7 * int(r["ref"][1:])),
                )
            )
        session.add_all(requests)
        session.commit()
        counts = {"accounts": len(accounts), "requesters": len(people), "requests": len(requests)}
        if snapshot:
            by_ref = {r["ref"]: req for r, req in zip(_read("requests.json"), requests, strict=True)}
            counts.update(apply_snapshot(session, by_ref))
        return counts


class SnapshotRelated(BaseModel):
    need_key: str
    label: Literal["same_need", "related"]
    model_confidence: float | None = Field(None, ge=0, le=1)
    rationale: str | None
    quotes: list[str]
    score: float


class SnapshotDecision(BaseModel):
    band: Literal["auto", "suggest", "new"]
    need_key: str | None
    score: float
    label: Literal["same_need"] | None
    model_confidence: float | None = Field(None, ge=0, le=1)
    rationale: str | None
    quotes: list[str]
    related: list[SnapshotRelated]

    @model_validator(mode="after")
    def _linked_bands_name_a_need(self) -> "SnapshotDecision":
        if self.band in ("auto", "suggest") and not self.need_key:
            raise ValueError(f"band {self.band} needs a need_key")
        return self


class SnapshotRun(BaseModel):
    step: Literal["extract", "adjudicate"]
    model: str
    prompt_version: str
    input_tokens: int
    output_tokens: int
    cost_usd: float
    latency_ms: int
    outcome: str


class SnapshotRequest(BaseModel):
    extraction: Extraction
    decision: SnapshotDecision
    runs: list[SnapshotRun]
    first_appearance: bool
    replay_need_key: str


def _check_snapshot(raw: dict[str, Any], routing: RoutingConfig) -> dict[str, SnapshotRequest]:
    """Validate recorded model output with the same schemas as live output, and refuse a snapshot that
    no longer matches the locked config or prompts (it would show decisions the app wouldn't make)."""
    expected = {"auto": routing.auto, "suggest": routing.suggest, "s_min": routing.s_min, "s_max": routing.s_max,
                "weights": [routing.w_label, routing.w_sim, routing.w_fields]}  # fmt: skip
    if raw.get("routing") != expected or raw.get("prompts") != ["extract_need_v1", "adjudicate_v1"]:
        raise ValueError(
            "snapshot.json was built for another routing config or prompt version: run `make snapshot`"
        )
    try:
        records = {ref: SnapshotRequest.model_validate(v) for ref, v in raw["requests"].items()}
    except ValidationError as exc:
        raise ValueError(f"snapshot.json does not validate: {exc}") from exc
    known = set(raw["needs"])
    for ref, rec in records.items():
        keys = [rec.decision.need_key] if rec.decision.band != "new" else []
        keys += [r.need_key for r in rec.decision.related]
        if rec.decision.band == "new" and rec.first_appearance:
            keys.append(rec.replay_need_key)
        missing = [k for k in keys if k not in known]
        if missing:
            raise ValueError(f"snapshot.json: {ref} points at unknown need(s) {missing}: run `make snapshot`")
    if sorted(raw.get("arrival_order", [])) != sorted(records):
        raise ValueError("snapshot.json: arrival_order doesn't list every request")
    return records


def apply_snapshot(session: Session, by_ref: dict[str, Request]) -> dict[str, int]:
    """Apply recorded Haiku output in arrival order, as the worker would have processed it."""
    raw = json.loads(SNAPSHOT.read_text(encoding="utf-8"))
    routing = load_routing(CONFIG / "routing.yaml")
    priorities = load_priorities(CONFIG / "priorities.yaml")
    records = _check_snapshot(raw, routing)
    needs: dict[str, Need] = {}

    def need_for(key: str, fallback: Extraction) -> Need:
        if key not in needs:
            info = raw["needs"].get(key)  # own:<ref> needs come from the request's own extraction
            need = Need(
                title=info["title"] if info else fallback.need_statement,
                problem=info["problem"] if info else fallback.problem,
                persona=info["persona"] if info else fallback.persona,
                job_to_be_done=fallback.job_to_be_done,
                product_area=info["product_area"] if info else fallback.product_area,
                created_by="ai",
            )
            session.add(need)
            session.flush()
            needs[key] = need
        return needs[key]

    runs = 0
    related: list[tuple[Request, SnapshotRelated, int | None]] = []
    for ref in raw["arrival_order"]:
        rec, req = records[ref], by_ref[ref]
        ex, d = rec.extraction, rec.decision
        text = redact(f"{req.title}\n{req.description}")
        req.redacted_text = text
        req.need_statement, req.problem, req.persona = ex.need_statement, ex.problem, ex.persona
        req.job_to_be_done, req.proposed_solution = ex.job_to_be_done, ex.proposed_solution
        req.product_area, req.severity_signal = ex.product_area, ex.severity_signal
        req.extraction_confidence, req.extraction_rationale = ex.confidence, ex.rationale
        latency = sum(r.latency_ms for r in rec.runs)
        req.status, req.attempts = RequestStatus.processed, 1
        req.processed_at = req.created_at + timedelta(milliseconds=latency)  # as if processed on arrival
        run_ids: list[int | None] = []
        for r in rec.runs:
            run = AIRun(request_id=req.id, **r.model_dump())
            session.add(run)
            session.flush()
            run_ids.append(run.id)
            runs += 1
        adjudicate_run = run_ids[-1] if len(run_ids) > 1 else None
        quotes, _dropped = verify_quotes(d.quotes, text)
        if d.band == "new":
            need = need_for(rec.replay_need_key if rec.first_appearance else f"own:{ref}", ex)
            sug = AISuggestion(
                request_id=req.id,
                need_id=need.id,
                kind=SuggestionKind.new_need,
                state=SuggestionState.applied,
                rationale=d.rationale,
                ai_run_id=run_ids[0] if run_ids else None,
            )
        else:
            assert d.need_key is not None
            need = need_for(d.need_key, ex)
            auto = d.band == "auto"
            sug = AISuggestion(
                request_id=req.id,
                need_id=need.id,
                kind=SuggestionKind.duplicate,
                label=d.label,
                routing_score=d.score,
                model_confidence=d.model_confidence,
                rationale=d.rationale,
                quotes=quotes,
                state=SuggestionState.applied if auto else SuggestionState.proposed,
                audit_sample=auto and in_audit_sample(req.id or 0, routing),
                ai_run_id=adjudicate_run,
            )
        session.add(sug)
        session.flush()
        if d.band in ("auto", "new") and need.id is not None:
            req.need_id = need.id
            session.add(
                LinkEvent(
                    action=LinkAction.link,
                    actor=LinkActor.auto,
                    need_id=need.id,
                    request_id=req.id,
                    suggestion_id=sug.id,
                    routing_score=d.score if d.band == "auto" else None,
                    reason="recorded (snapshot.json)",
                )
            )
        session.add(req)
        related += [(req, x, adjudicate_run) for x in d.related]
    for req, x, run_id in related:  # informational, only to needs that exist in the seeded backlog
        if x.need_key in needs:
            kept, _ = verify_quotes(x.quotes, req.redacted_text or "")
            session.add(
                AISuggestion(
                    request_id=req.id,
                    need_id=needs[x.need_key].id,
                    kind=SuggestionKind.related,
                    label=x.label,
                    routing_score=x.score,
                    model_confidence=x.model_confidence,
                    rationale=x.rationale,
                    quotes=kept,
                    ai_run_id=run_id,
                )
            )
    session.flush()
    for need in needs.values():
        if need.id is not None:
            refresh_need(session, need.id, priorities)
    session.commit()
    return {"needs": len(needs), "ai_runs": runs}


def main() -> None:
    raw = "--raw" in sys.argv
    engine = get_engine()
    counts = load_seed(engine, snapshot=not raw)
    if raw:
        print(
            f"Seeded {engine.url}: {counts['accounts']} accounts, {counts['requesters']} requesters, "
            f"{counts['requests']} pending requests, 0 needs"
        )
    else:
        print(
            f"Seeded {engine.url}: {counts['accounts']} accounts, {counts['requesters']} requesters, "
            f"{counts['requests']} requests processed from snapshot.json (recorded Haiku 4.5 output), "
            f"{counts['needs']} needs, {counts['ai_runs']} AI runs"
        )


if __name__ == "__main__":
    main()
