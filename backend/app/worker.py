"""The database is the queue (ADR 0007): one pending row at a time, retries with backoff, stale reclaim.

A request row is its own job: pending -> processing (attempts + 1, claimed_at) -> processed, or back to
pending after a transient error, or needs_review after a terminal error or the last attempt. Claimed
supports go through the same loop with their own check_* columns; their dead end is "disputed".
"""

import asyncio
import logging
import time
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy.engine import Engine
from sqlmodel import Session, col, select

from app.ai.gateway import TerminalError, TransientError
from app.ai.pipeline import Deps, dispute_claim, process_claim, process_request
from app.models import Request, RequestStatus, Support, SupportLinkStatus, utcnow

log = logging.getLogger("distill.worker")


@dataclass(frozen=True)
class WorkerConfig:
    max_attempts: int = 3
    lease_seconds: int = 600  # above the worst case: 30 s x 3 SDK tries x 2 gateway tries x 2 steps
    reclaim_every_seconds: float = 60.0
    backoff_base_seconds: float = 5.0


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
            s.commit()
        if stale:
            log.warning("reclaimed %d request(s) left in processing", len(stale))
        return len(stale)

    def run_once(self, now: datetime | None = None) -> str | None:
        now = now or utcnow()
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
                self._claim(s, sup.id)
                return f"claim:{sup.id}"
        return None

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
