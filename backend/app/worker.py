"""The database is the queue (ADR 0007): one pending row at a time, retries with backoff, stale reclaim.

A request row is its own job: pending -> processing (attempts + 1, claimed_at) -> processed, or back to
pending after a transient error, or needs_review after a terminal error or the last attempt. Claimed
supports go through the same loop with their own check_* columns; their dead end is "disputed".
Strategic-fit ratings come last (fit_* columns on the need): requests and claims are never kept waiting by
them, and their dead end is "failed", which leaves the ratings in use unchanged. Offline mode has no rater.
"""

import asyncio
import logging
import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy.engine import Engine
from sqlmodel import Session, col, func, select

from app.ai.gateway import TerminalError, TransientError
from app.ai.pipeline import Deps, dispute_claim, process_claim, process_fit, process_request
from app.models import (
    AIRun,
    Brief,
    Need,
    NeedStatus,
    NeedStatusChange,
    Request,
    RequestStatus,
    Support,
    SupportLinkStatus,
    utcnow,
)
from app.observability import request_id
from app.services.briefs import process_brief
from app.services.briefs import trace_id as brief_trace
from app.services.updates import process_drafts

log = logging.getLogger("distill.worker")


@dataclass(frozen=True)
class WorkerConfig:
    max_attempts: int = 3
    lease_seconds: int = 600  # above the worst case: 30 s x 3 SDK tries x 2 gateway tries x 2 steps
    brief_lease_seconds: int = 3600  # a brief is up to 9 agent turns plus brief calls with a 180 s timeout
    reclaim_every_seconds: float = 60.0
    backoff_base_seconds: float = 5.0
    daily_budget_usd: float | None = (
        None  # stop claiming jobs once today's model spend reaches this (live only)
    )


@contextmanager
def traced(rid: str) -> Iterator[None]:
    """Run a queue job under a request ID, so its logs and ai_runs can be traced back."""
    token = request_id.set(rid)
    try:
        yield
    finally:
        request_id.reset(token)


def _aware(t: datetime) -> datetime:
    return t if t.tzinfo else t.replace(tzinfo=UTC)


class Worker:
    def __init__(self, engine: Engine, deps: Deps, cfg: WorkerConfig | None = None) -> None:
        self.engine, self.deps, self.cfg = engine, deps, cfg or WorkerConfig()

    def _ready(self, attempts: int, last_try: datetime | None, now: datetime) -> bool:
        if attempts == 0 or last_try is None:
            return True
        return _aware(last_try) + timedelta(seconds=self.cfg.backoff_base_seconds * 2**attempts) <= now

    def reclaim_stale(self, now: datetime | None = None, lease_seconds: int | None = None) -> int:
        """Rows left in processing go back to pending once their lease has expired.

        At startup the lease is 0: with one worker, anything still in processing was interrupted.
        """
        now = now or utcnow()
        lease = self.cfg.lease_seconds if lease_seconds is None else lease_seconds
        cutoff = now - timedelta(seconds=lease)
        with Session(self.engine) as s:
            rows = s.exec(select(Request).where(Request.status == RequestStatus.processing)).all()
            stale = [r for r in rows if r.claimed_at is None or _aware(r.claimed_at) <= cutoff]
            for r in stale:
                r.status = RequestStatus.pending
                s.add(r)
            brief_cutoff = now - timedelta(
                seconds=self.cfg.brief_lease_seconds if lease_seconds is None else lease
            )
            briefs = s.exec(select(Brief).where(Brief.status == "processing")).all()
            stuck = [b for b in briefs if b.started_at is None or _aware(b.started_at) <= brief_cutoff]
            for b in stuck:
                b.status = "pending"
                s.add(b)
            s.commit()
        if stale or stuck:
            log.warning("reclaimed %d request(s) and %d brief(s) left in processing", len(stale), len(stuck))
        return len(stale) + len(stuck)

    def spent_today(self, now: datetime) -> float:
        midnight = now.replace(hour=0, minute=0, second=0, microsecond=0)
        with Session(self.engine) as s:
            total = s.exec(select(func.sum(AIRun.cost_usd)).where(col(AIRun.created_at) >= midnight)).one()
        return float(total or 0.0)

    def over_budget(self, now: datetime) -> bool:
        """A spend ceiling, so a flood of submissions or toggled statuses can't run up the bill: jobs wait
        (nothing is lost) until the next UTC day or a higher budget. Offline mode costs nothing."""
        if self.deps.mode != "llm" or self.cfg.daily_budget_usd is None:
            return False
        if self.spent_today(now) < self.cfg.daily_budget_usd:
            return False
        log.warning("daily model budget reached (%.2f USD); jobs wait", self.cfg.daily_budget_usd)
        return True

    def run_once(self, now: datetime | None = None) -> str | None:
        now = now or utcnow()
        if self.over_budget(now):
            return None
        with Session(self.engine) as s:
            pending = s.exec(
                select(Request)
                .where(Request.status == RequestStatus.pending)
                .order_by(col(Request.created_at), col(Request.id))
            ).all()
            r = next((x for x in pending if self._ready(x.attempts, x.claimed_at, now)), None)
            if r is not None and r.id is not None:
                r.status, r.attempts, r.claimed_at = RequestStatus.processing, r.attempts + 1, now
                s.add(r)
                s.commit()
                with traced(r.trace_id or f"request-{r.id}"):  # the submission's request ID, into its ai_runs
                    self._request(s, r.id)
                return f"request:{r.id}"
            claims = s.exec(
                select(Support)
                .where(Support.link_status == SupportLinkStatus.claimed)
                .order_by(col(Support.created_at))
            ).all()
            sup = next((x for x in claims if self._ready(x.check_attempts, x.check_started_at, now)), None)
            if sup is not None and sup.id is not None:
                sup.check_attempts, sup.check_started_at = sup.check_attempts + 1, now
                s.add(sup)
                s.commit()
                with traced(f"claim-{sup.id}"):
                    self._claim(s, sup.id)
                return f"claim:{sup.id}"
            changes = s.exec(
                select(NeedStatusChange)
                .where(NeedStatusChange.drafts_status == "pending")
                .order_by(col(NeedStatusChange.created_at), col(NeedStatusChange.id))
            ).all()
            change = next(
                (c for c in changes if self._ready(c.drafts_attempts, c.drafts_started_at, now)), None
            )
            if change is not None and change.id is not None:  # offline mode drafts from a template
                change.drafts_attempts, change.drafts_started_at = change.drafts_attempts + 1, now
                s.add(change)
                s.commit()
                with traced(f"status-change-{change.id}"):
                    self._drafts(s, change.id)
                return f"drafts:{change.id}"
            asked = s.exec(
                select(Brief).where(Brief.status == "pending").order_by(col(Brief.created_at), col(Brief.id))
            ).all()
            brief = next((x for x in asked if self._ready(x.attempts, x.started_at, now)), None)
            if (
                brief is not None and brief.id is not None
            ):  # offline mode briefs from the baseline and a template
                brief.status, brief.attempts, brief.started_at = "processing", brief.attempts + 1, now
                s.add(brief)
                s.commit()
                with traced(brief_trace(brief.id)):
                    self._brief(s, brief.id)
                return f"brief:{brief.id}"
            if self.deps.mode != "llm":
                return None
            due = s.exec(
                select(Need)
                .where(Need.fit_status == "pending", Need.status != NeedStatus.merged)
                .order_by(col(Need.created_at), col(Need.id))
            ).all()
            need = next((x for x in due if self._ready(x.fit_attempts, x.fit_started_at, now)), None)
            if need is not None and need.id is not None:
                need.fit_attempts, need.fit_started_at = need.fit_attempts + 1, now
                s.add(need)
                s.commit()
                with traced(f"fit-{need.id}"):
                    self._fit(s, need.id)
                return f"fit:{need.id}"
        return None

    def _drafts(self, s: Session, change_id: int) -> None:
        try:
            process_drafts(s, change_id, self.deps)
        except Exception as exc:  # transient errors retry with backoff; anything else fails the drafting now
            s.rollback()
            change = s.get(NeedStatusChange, change_id)
            assert change is not None
            transient = isinstance(exc, TransientError)
            reason = (
                str(exc)
                if isinstance(exc, TransientError | TerminalError)
                else f"internal error: {type(exc).__name__}: {exc}"
            )
            if transient and change.drafts_attempts < self.cfg.max_attempts:
                change.drafts_error = reason
            else:  # the status stands; the PM writes the messages, or retries later
                change.drafts_status, change.drafts_error = "failed", reason
            s.add(change)
            s.commit()

    def _brief(self, s: Session, brief_id: int) -> None:
        try:
            process_brief(s, brief_id, self.deps)
        except Exception as exc:  # transient errors retry with backoff; anything else fails the brief now
            s.rollback()
            b = s.get(Brief, brief_id)
            assert b is not None
            transient = isinstance(exc, TransientError)
            reason = (
                str(exc)
                if isinstance(exc, TransientError | TerminalError)
                else f"internal error: {type(exc).__name__}: {exc}"
            )
            b.error = reason
            b.status = "pending" if transient and b.attempts < self.cfg.max_attempts else "failed"
            s.add(b)
            s.commit()

    def _fit(self, s: Session, need_id: int) -> None:
        try:
            process_fit(s, need_id, self.deps)
        except Exception as exc:  # transient errors retry with backoff; anything else fails the rating now
            s.rollback()
            need = s.get(Need, need_id)
            assert need is not None
            transient = isinstance(exc, TransientError)
            reason = (
                str(exc)
                if isinstance(exc, TransientError | TerminalError)
                else f"internal error: {type(exc).__name__}: {exc}"
            )
            if transient and need.fit_attempts < self.cfg.max_attempts:
                need.fit_error = reason
            else:
                need.fit_status = "failed"
                need.fit_error = (
                    f"Rating failed after {need.fit_attempts} attempts; last error: {reason}"
                    if transient
                    else reason
                )
            s.add(need)
            s.commit()

    def _request(self, s: Session, request_id: int) -> None:
        try:
            process_request(s, request_id, self.deps)
        except TransientError as exc:
            s.rollback()
            r = s.get(Request, request_id)
            assert r is not None
            r.last_error = str(exc)
            if r.attempts >= self.cfg.max_attempts:
                r.status = RequestStatus.needs_review
                r.needs_review_reason = f"Provider failed {r.attempts} attempts; last error: {exc}"
            else:
                r.status = RequestStatus.pending
            s.add(r)
            s.commit()
        except Exception as exc:  # terminal, or a bug: never leave the row stuck in processing
            s.rollback()
            r = s.get(Request, request_id)
            assert r is not None
            reason = (
                str(exc) if isinstance(exc, TerminalError) else f"internal error: {type(exc).__name__}: {exc}"
            )
            r.status, r.last_error, r.needs_review_reason = RequestStatus.needs_review, reason, reason
            s.add(r)
            s.commit()

    def _claim(self, s: Session, support_id: int) -> None:
        try:
            process_claim(s, support_id, self.deps)
        except TransientError as exc:
            s.rollback()
            sup = s.get(Support, support_id)
            assert sup is not None
            sup.check_error = str(exc)
            if sup.check_attempts >= self.cfg.max_attempts:
                dispute_claim(
                    s,
                    sup,
                    f"could not check the claim after {sup.check_attempts} attempts; last error: {exc}",
                )
            s.add(sup)
            s.commit()
        except Exception as exc:
            s.rollback()
            sup = s.get(Support, support_id)
            assert sup is not None
            reason = (
                str(exc) if isinstance(exc, TerminalError) else f"internal error: {type(exc).__name__}: {exc}"
            )
            sup.check_error = reason
            dispute_claim(s, sup, reason)
            s.commit()

    def tick(self) -> str | None:
        """run_once that can't raise: an error outside the pipeline (e.g. "database is locked") is logged."""
        try:
            done = self.run_once()
        except Exception:
            log.exception("worker step failed; retrying shortly")
            return None
        if done:
            log.info("processed %s", done)
        return done

    async def run_forever(self, idle_seconds: float = 1.0) -> None:
        """Process rows until cancelled. DB and model work run in a thread so the API stays responsive.
        Stale claims are reclaimed periodically too, with the lease (ADR 0007)."""
        last_reclaim = time.monotonic()
        while True:
            if time.monotonic() - last_reclaim > self.cfg.reclaim_every_seconds:
                await asyncio.to_thread(self.reclaim_stale)
                last_reclaim = time.monotonic()
            done = await asyncio.to_thread(self.tick)
            if done is None:
                await asyncio.sleep(idle_seconds)
