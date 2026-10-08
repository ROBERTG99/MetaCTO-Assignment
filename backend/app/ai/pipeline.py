"""The intake workflow (ADR 0001): redact, embed, retrieve, extract, adjudicate, route, mark processed.

It then queues a strategic-fit rating when one is due; demand, urgency and priority are computed on read
(app/services/priority.py, ADR 0009), not here.

Model calls happen first; every result is written in one transaction with status processed, so a retry
never leaves half a decision behind (ADR 0007). AIRuns are written separately, so failed calls still count.
"""

import html
import logging
import re
from dataclasses import dataclass
from typing import Literal

from sqlmodel import Session, col, select

from app.ai.baseline import Thresholds
from app.ai.baseline import route as baseline_route
from app.ai.gateway import Gateway
from app.ai.index import NeedSearch, request_text
from app.ai.policy import (
    Route,
    RoutingConfig,
    Scored,
    claim_confirmed,
    decide,
    in_audit_sample,
    routing_score,
)
from app.ai.redact import redact
from app.ai.retrieval import Hit
from app.ai.schemas import Adjudication, CandidateNeed, Extraction
from app.models import (
    AISuggestion,
    GoalRating,
    LinkAction,
    LinkActor,
    LinkEvent,
    Need,
    NeedStatus,
    Request,
    Requester,
    RequestStatus,
    SuggestionKind,
    SuggestionState,
    Support,
    SupportLinkStatus,
    utcnow,
)
from app.scoring import PrioritiesConfig, goals_digest
from app.services.priority import account_count, queue_fit_if_due

log = logging.getLogger("distill.pipeline")


@dataclass
class Deps:
    gateway: Gateway
    search: NeedSearch
    routing: RoutingConfig
    priorities: PrioritiesConfig
    mode: Literal["llm", "baseline"] = "llm"
    baseline: Thresholds | None = None


def _same(a: str | None, b: str | None) -> bool:
    return bool(a and b and a.strip().lower() == b.strip().lower())


def _candidates(
    session: Session, text: str, deps: Deps, also: int | None = None
) -> tuple[dict[int, Need], dict[int, float]]:
    """Live candidate needs and their best similarity. `also` (a claimed need) is included while it is live.

    Asks the index for more than k, so merged needs don't take up candidate slots.
    """
    ranked = deps.search.search(text, k=deps.routing.top_k * 3)
    found = {
        n.id: n
        for n in session.exec(select(Need).where(col(Need.id).in_([i for i, _ in ranked]))).all()
        if n.id
    }
    sims = {i: sim for i, sim in ranked if i in found and found[i].status != NeedStatus.merged}
    sims = dict(list(sims.items())[: deps.routing.top_k])
    if also is not None and also not in sims:
        claimed = session.get(Need, also)
        if claimed is not None and claimed.status != NeedStatus.merged:
            found[also] = claimed
            sims[also] = dict(deps.search.search(text, k=10_000)).get(also, 0.0)
    return {i: found[i] for i in sims}, sims


def _candidate(session: Session, need: Need) -> CandidateNeed:
    examples = session.exec(select(Request.title).where(Request.need_id == need.id).limit(2)).all()
    return _candidate_from(need, list(examples))


def _candidate_from(need: Need, examples: list[str]) -> CandidateNeed:
    """What the adjudicator sees of a need (also used by the evals, which have no database)."""
    return CandidateNeed(
        id=str(need.id),
        title=need.title,
        problem=need.problem or need.title,
        persona=need.persona,
        product_area=need.product_area,
        examples=examples[:2],
    )


def _score(
    adj: Adjudication, needs: dict[int, Need], sims: dict[int, float], ex: Extraction, cfg: RoutingConfig
) -> list[Scored]:
    """One Scored per known candidate. Ids the model made up are ignored; a candidate it skipped is "different"."""
    labels: dict[int, str] = {}
    for j in adj.judgments:
        if j.candidate_id.isdigit() and int(j.candidate_id) in needs and int(j.candidate_id) not in labels:
            labels[int(j.candidate_id)] = j.label
    scored = []
    for nid, need in needs.items():
        label = labels.get(nid, "different")
        area, persona = _same(ex.product_area, need.product_area), _same(ex.persona, need.persona)
        scored.append(
            Scored(nid, label, sims[nid], area, persona, routing_score(label, sims[nid], area, persona, cfg))
        )
    return scored


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(text)).strip().lower()


def verify_quotes(quotes: list[str], source: str) -> tuple[list[str], int]:
    """Keep the quotes found in the text the model was given; count the rest (spec §6 step 5)."""
    haystack = _norm(source)
    kept = [q for q in quotes if q.strip() and _norm(q) in haystack]
    return kept, len(quotes) - len(kept)


def _judgment(
    adj: Adjudication | None, need_id: int | None, source: str
) -> tuple[float | None, str | None, list[str]]:
    for j in adj.judgments if adj else []:
        if j.candidate_id == str(need_id):
            kept, dropped = verify_quotes(j.quotes, source)
            note = (
                f" ({dropped} quote{'s' if dropped > 1 else ''} dropped: not found in the request)"
                if dropped
                else ""
            )
            return j.confidence, j.rationale + note, kept
    return None, None, []


def _extracted(ex: Extraction) -> str:
    return f"{ex.need_statement} (persona: {ex.persona}; area: {ex.product_area})"


def live_need(session: Session, need_id: int | None) -> int | None:
    """Follow merged_into_id to the need that is live now (a PM may merge while a model call is running)."""
    seen: set[int] = set()
    while need_id is not None and need_id not in seen:
        seen.add(need_id)
        need = session.get(Need, need_id)
        if need is None:
            return None
        if need.status != NeedStatus.merged:
            return need_id
        need_id = need.merged_into_id
    return None


def _link(session: Session, r: Request, need_id: int, actor: LinkActor, suggestion: AISuggestion | None,
          score: float | None, by: str | None = None, reason: str | None = None) -> None:  # fmt: skip
    r.need_id = need_id
    session.add(
        LinkEvent(
            action=LinkAction.link,
            actor=actor,
            actor_id=by,
            need_id=need_id,
            request_id=r.id,
            suggestion_id=suggestion.id if suggestion else None,
            routing_score=score,
            reason=reason,
        )
    )


def new_need_for(session: Session, r: Request, created_by: str) -> Need:
    need = Need(
        title=r.need_statement or r.title,
        problem=r.problem or r.title,
        persona=r.persona,
        job_to_be_done=r.job_to_be_done,
        product_area=r.product_area,
        created_by=created_by,
    )
    session.add(need)
    session.flush()
    return need


def _already_decided(session: Session, r: Request) -> bool:
    if r.need_id is not None:
        return True
    return (
        session.exec(
            select(AISuggestion).where(
                AISuggestion.request_id == r.id,
                col(AISuggestion.kind).in_([SuggestionKind.duplicate, SuggestionKind.new_need]),
            )
        ).first()
        is not None
    )


def process_request(session: Session, request_id: int, deps: Deps) -> str:
    r = session.get(Request, request_id)
    if r is None:
        raise ValueError(f"request {request_id} not found")
    if r.status == RequestStatus.processed or _already_decided(session, r):
        if r.status != RequestStatus.processed:  # a stale reclaim after the commit: nothing to redo
            r.status, r.processed_at = RequestStatus.processed, r.processed_at or utcnow()
            session.add(r)
            session.commit()
        return "done"
    text = redact(f"{r.title}\n{r.description}")
    requester = session.get(Requester, r.requester_id)
    role = requester.role if requester else None
    needs, sims = _candidates(session, text, deps)
    ex, ex_run = deps.gateway.extract(text=text, why=None, role=role, request_id=r.id)
    adj: Adjudication | None = None
    adj_run: int | None = None
    scored: list[Scored] = []
    if deps.mode == "baseline":
        assert deps.baseline is not None
        hits = [Hit(str(i), s, "") for i, s in sorted(sims.items(), key=lambda kv: (-kv[1], kv[0]))]
        b = baseline_route(hits, deps.baseline)
        route = Route(b.band, int(b.need_id) if b.need_id else None, b.score)
    else:
        if needs:
            adj, adj_run = deps.gateway.adjudicate(
                text=text,
                why=None,
                candidates=[_candidate(session, n) for n in needs.values()],
                request_id=r.id,
                role=role,
                extracted=_extracted(ex),
            )
            scored = _score(adj, needs, sims, ex, deps.routing)
        route = decide(scored, deps.routing)
    if route.need_id is not None:  # the chosen need may have been merged while we waited on the model
        target = live_need(session, route.need_id)
        route = Route(route.band, target, route.score) if target else Route("new", None, route.score)

    r.redacted_text = text
    r.need_statement, r.problem, r.persona = ex.need_statement, ex.problem, ex.persona
    r.job_to_be_done, r.proposed_solution, r.product_area = (
        ex.job_to_be_done,
        ex.proposed_solution,
        ex.product_area,
    )
    r.severity_signal, r.extraction_confidence, r.extraction_rationale = (
        ex.severity_signal,
        ex.confidence,
        ex.rationale,
    )
    first_choice = next(
        (s.need_id for s in scored if s.score == route.score and s.label == "same_need"), route.need_id
    )
    confidence, rationale, quotes = _judgment(adj, first_choice, text)
    label = "same_need" if deps.mode == "llm" and route.need_id else ("similar" if route.need_id else None)
    chosen = next((s for s in scored if s.need_id == first_choice), None)
    if deps.mode == "baseline" and route.need_id is not None and deps.baseline is not None:
        rationale = baseline_reason(route.score, deps.baseline)
    if route.band in ("auto", "suggest"):
        assert route.need_id is not None
        auto = route.band == "auto"
        sug = AISuggestion(
            request_id=r.id,
            need_id=route.need_id,
            kind=SuggestionKind.duplicate,
            label=label,
            routing_score=route.score,
            routing_mode=deps.mode,
            similarity=chosen.similarity if chosen else (route.score if deps.mode == "baseline" else None),
            area_match=chosen.area_match if chosen else None,
            persona_match=chosen.persona_match if chosen else None,
            model_confidence=confidence,
            rationale=rationale,
            quotes=quotes,
            state=SuggestionState.applied if auto else SuggestionState.proposed,
            audit_sample=auto and in_audit_sample(r.id or 0, deps.routing),
            ai_run_id=adj_run or ex_run,
        )
        session.add(sug)
        session.flush()
        if auto:
            _link(session, r, route.need_id, LinkActor.auto, sug, route.score)
    else:
        need = new_need_for(session, r, "ai")
        sug = AISuggestion(
            request_id=r.id,
            need_id=need.id,
            kind=SuggestionKind.new_need,
            state=SuggestionState.applied,
            rationale="No existing need matched; created a new one.",
            ai_run_id=ex_run,
        )
        session.add(sug)
        session.flush()
        assert need.id is not None
        _link(session, r, need.id, LinkActor.auto, sug, None)
    for s in scored:  # near misses too: a same_need below the bands is worth showing as related
        if s.label in ("related", "same_need") and s.need_id not in (first_choice, route.need_id):
            c, why, q = _judgment(adj, s.need_id, text)
            session.add(
                AISuggestion(
                    request_id=r.id,
                    need_id=s.need_id,
                    kind=SuggestionKind.related,
                    label=s.label,
                    routing_score=s.score,
                    routing_mode=deps.mode,
                    similarity=s.similarity,
                    area_match=s.area_match,
                    persona_match=s.persona_match,
                    model_confidence=c,
                    rationale=why,
                    quotes=q,
                    ai_run_id=adj_run,
                )
            )
    if r.need_id is not None:
        queue_fit_if_due(session, r.need_id, deps.priorities)
    r.status, r.processed_at = RequestStatus.processed, utcnow()
    session.add(r)
    session.commit()
    try:  # the commit is the decision; the index catches up here, or is rebuilt at the next startup
        if r.need_id is not None and r.id is not None:
            if route.band == "new":
                new = session.get(Need, r.need_id)
                if new is not None:
                    deps.search.add_need(new)
            deps.search.add_request(r.id, r.need_id, request_text(r))
    except Exception:
        log.exception("index update failed for request %s; it will be rebuilt at startup", r.id)
    return route.band


def baseline_reason(score: float, t: Thresholds) -> str:
    """Offline mode has no model to explain itself, so the routing is explained in words (rule 6)."""
    band = "auto-link" if score >= t.auto else "suggest" if score >= t.suggest else "new need"
    return (
        f"Offline baseline: the request's embedding is {score:.3f} similar to this need. Auto-link at "
        f"{t.auto:.3f} or more, suggest at {t.suggest:.3f} or more, so: {band}. No model judged it."
    )


def claim_baseline_reason(similarity: float, t: Thresholds) -> str:
    """Why the offline baseline disputed a claim, in words (rule 6)."""
    return (
        f"Offline baseline: the reason given for this claim is {similarity:.3f} similar to the claimed need. A claim "
        f"is confirmed at {t.suggest:.3f} or more, so a PM decides. No model judged it."
    )


def dispute_claim(session: Session, sup: Support, reason: str, alternative: int | None = None,
                  rationale: str | None = None, score: float | None = None, run_id: int | None = None,
                  parts: Scored | None = None, mode: str | None = None) -> None:  # fmt: skip
    """The claim stays uncounted and goes to the PM inbox (Disputed claims)."""
    sup.link_status, sup.review_reason, sup.updated_at = SupportLinkStatus.disputed, reason, utcnow()
    session.add(sup)
    session.add(
        AISuggestion(
            support_id=sup.id,
            need_id=alternative or sup.need_id,
            kind=SuggestionKind.duplicate,
            state=SuggestionState.proposed,
            rationale=rationale or reason,
            routing_score=score,
            label=parts.label if parts else None,
            routing_mode=mode if parts else None,
            similarity=parts.similarity if parts else None,
            area_match=parts.area_match if parts and mode != "baseline" else None,
            persona_match=parts.persona_match if parts and mode != "baseline" else None,
            ai_run_id=run_id,
        )
    )


def process_claim(session: Session, support_id: int, deps: Deps) -> str:
    """Check a requester claim: the requester's own reason is the text judged, never the title they clicked."""
    sup = session.get(Support, support_id)
    if sup is None:
        raise ValueError(f"support {support_id} not found")
    if sup.link_status != SupportLinkStatus.claimed:
        return "done"
    why = (sup.why_it_matters or "").strip()
    if not why:
        dispute_claim(session, sup, "no reason given to check the claim against")
        session.commit()
        return "disputed"
    requester = session.get(Requester, sup.requester_id)
    role = requester.role if requester else None
    text = redact(why)
    needs, sims = _candidates(session, text, deps, also=sup.need_id)
    if sup.need_id not in needs:  # the claimed need was merged away: a PM decides
        dispute_claim(session, sup, "the claimed need is no longer open")
        session.commit()
        return "disputed"
    ex, ex_run = deps.gateway.extract(text=text, why=None, role=role)
    best_other: Scored | None = None
    if deps.mode == "baseline":
        assert deps.baseline is not None
        sim = sims.get(sup.need_id, 0.0)
        label = "same_need" if sim >= deps.baseline.suggest else "different"
        claimed: Scored | None = Scored(sup.need_id, "similar" if label == "same_need" else "different", sim,
                                        False, False, sim)  # fmt: skip
        confirmed = label == "same_need"
        adj_run: int | None = None
    else:
        adj, adj_run = deps.gateway.adjudicate(
            text=text,
            why=None,
            candidates=[_candidate(session, n) for n in needs.values()],
            role=role,
            extracted=_extracted(ex),
        )
        scored = _score(adj, needs, sims, ex, deps.routing)
        claimed = next((s for s in scored if s.need_id == sup.need_id), None)
        others = [s for s in scored if s.need_id != sup.need_id and s.label == "same_need"]
        best_other = max(others, key=lambda s: s.score, default=None)
        confirmed = claim_confirmed(claimed, deps.routing)
    if confirmed:
        assert claimed is not None
        sup.link_status, sup.updated_at = SupportLinkStatus.confirmed, utcnow()
        session.add(sup)
        session.add(
            AISuggestion(
                support_id=sup.id,
                need_id=sup.need_id,
                kind=SuggestionKind.duplicate,
                state=SuggestionState.applied,
                label=claimed.label,
                routing_score=claimed.score,
                routing_mode=deps.mode,
                similarity=claimed.similarity,
                area_match=claimed.area_match if deps.mode == "llm" else None,
                persona_match=claimed.persona_match if deps.mode == "llm" else None,
                ai_run_id=adj_run or ex_run,
            )
        )
        session.flush()
        queue_fit_if_due(session, sup.need_id, deps.priorities)
        session.commit()
        return "confirmed"
    offline = deps.mode == "baseline" and deps.baseline is not None and claimed is not None
    dispute_claim(
        session,
        sup,
        claim_baseline_reason(claimed.similarity, deps.baseline)  # type: ignore[arg-type,union-attr]
        if offline
        else "the model does not read this as the same need",
        alternative=best_other.need_id if best_other else None,
        score=claimed.score if claimed else None,
        run_id=adj_run or ex_run,
        parts=claimed,
        mode=deps.mode,
    )
    session.commit()
    return "disputed"


FIT_MAX_TEXTS, FIT_MAX_CHARS = 8, 1500


def fit_texts(session: Session, need_id: int) -> list[str]:
    """What the strategic-fit step reads: member requests, then confirmed supporters' reasons, oldest first,
    redacted and capped. Never who wrote them (role, account, segment, revenue): fit is judged on the problem."""
    members = session.exec(
        select(Request).where(Request.need_id == need_id).order_by(col(Request.created_at), col(Request.id))
    ).all()
    whys = session.exec(
        select(Support.why_it_matters)
        .where(Support.need_id == need_id, Support.link_status == SupportLinkStatus.confirmed)
        .order_by(col(Support.created_at), col(Support.id))
    ).all()
    texts = [r.redacted_text or redact(f"{r.title}\n{r.description}") for r in members]
    texts += [redact(w) for w in whys if w and w.strip()]
    return [t.strip()[:FIT_MAX_CHARS] for t in texts if t.strip()][:FIT_MAX_TEXTS]


def process_fit(session: Session, need_id: int, deps: Deps) -> str:
    """Rate a need against each goal (strategic_fit_v1) and point the need at the new ratings.

    One GoalRating row per goal; a quote not found in the requests the model was given is dropped and flagged.
    S itself is never stored: it is computed with the current goal weights when the need is read (ADR 0009).
    """
    need = session.get(Need, need_id)
    if need is None:
        raise ValueError(f"need {need_id} not found")
    if need.status == NeedStatus.merged and need.fit_status == "pending":  # merged while it waited
        need.fit_status = None
        session.add(need)
        session.commit()
    if need.fit_status != "pending":
        return "done"
    texts = fit_texts(session, need_id)
    out, run_id = deps.gateway.rate_fit(
        title=need.title,
        problem=need.problem or need.title,
        persona=need.persona,
        job_to_be_done=need.job_to_be_done,
        requests=texts,
        goals=deps.priorities.goals,
        need_id=need_id,
    )
    source = "\n".join(texts)
    for r in out.ratings:
        kept, dropped = verify_quotes([r.quote], source) if r.quote.strip() else ([], 0)
        session.add(
            GoalRating(
                need_id=need_id,
                ai_run_id=run_id,
                goal=r.goal,
                rating=r.rating,
                rationale=r.rationale,
                quote=kept[0] if kept else None,
                quote_dropped=bool(dropped),
            )
        )
    need.fit_run_id, need.fit_status, need.fit_error = run_id, "rated", None
    need.fit_goals_digest = goals_digest(deps.priorities.goals)
    need.fit_accounts = account_count(session, need_id)
    need.updated_at = utcnow()
    session.add(need)
    session.commit()
    return "rated"
