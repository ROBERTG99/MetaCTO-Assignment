from typing import Any

from fastapi import APIRouter, Depends
from sqlmodel import Session

from app.db import get_session
from app.schemas import OpsMetrics
from app.services import metrics

router = APIRouter(tags=["metrics"])


@router.get(
    "/metrics",
    response_model=OpsMetrics,
    summary="AI Ops and the success metrics (spec §10): calls, cost, latency, acceptance, false merges, M1-M3",
)
def overview(session: Session = Depends(get_session)) -> dict[str, Any]:
    return metrics.overview(session)
