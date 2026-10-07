from fastapi import APIRouter, Depends
from sqlmodel import Session

from app.ai.pipeline import Deps
from app.api.deps import get_deps
from app.db import get_session
from app.schemas import QuadrantView
from app.services import priority

router = APIRouter(tags=["insights"])


@router.get(
    "/insights/quadrant",
    response_model=QuadrantView,
    summary="Undecided needs by popularity and strategic fit",
    description="Popular is revenue-weighted demand (D), strategic is the goal-weighted fit (S); cut-offs "
    "come from config/priorities.yaml. Needs whose fit isn't rated yet are listed apart.",
)
def quadrant(session: Session = Depends(get_session), deps: Deps = Depends(get_deps)) -> QuadrantView:
    return priority.quadrant_view(session, deps.priorities)
