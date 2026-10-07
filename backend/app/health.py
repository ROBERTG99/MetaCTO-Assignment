"""Liveness, readiness and queue health (production readiness)."""

from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import text
from sqlalchemy.engine import Engine
from sqlmodel import Session, col, func, select

from app.models import Need, NeedStatusChange, Request, RequestStatus, Support, SupportLinkStatus


def ping_database(engine: Engine) -> None:
    with Session(engine) as s:
        s.exec(text("SELECT 1"))  # type: ignore[call-overload]


def _aware(t: datetime) -> datetime:
    return t if t.tzinfo else t.replace(tzinfo=UTC)


def queue_stats(session: Session, now: datetime | None = None, lease_seconds: int = 600) -> dict[str, Any]:
    """Queue depth and stuck claims: rows processing past their lease mean the worker died or hangs."""
    now = now or datetime.now(UTC)

    def count(model: Any, *where: Any) -> int:
        return int(session.exec(select(func.count()).select_from(model).where(*where)).one())

    processing = session.exec(
        select(Request.claimed_at).where(Request.status == RequestStatus.processing)
    ).all()
    oldest = session.exec(
        select(Request.created_at)
        .where(Request.status == RequestStatus.pending)
        .order_by(col(Request.created_at))
    ).first()
    cutoff = now - timedelta(seconds=lease_seconds)
    return {
        "pending": count(Request, Request.status == RequestStatus.pending),
        "processing": len(processing),
        "stuck": sum(1 for t in processing if t is None or _aware(t) <= cutoff),
        "needs_review": count(Request, Request.status == RequestStatus.needs_review),
        "claims_pending": count(Support, Support.link_status == SupportLinkStatus.claimed),
        "fit_pending": count(Need, Need.fit_status == "pending"),
        "drafts_pending": count(NeedStatusChange, NeedStatusChange.drafts_status == "pending"),
        "oldest_pending_seconds": round((now - _aware(oldest)).total_seconds(), 1) if oldest else None,
    }
