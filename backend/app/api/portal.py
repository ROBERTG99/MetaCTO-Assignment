from typing import Any

from fastapi import APIRouter, Depends, Path, Query
from sqlmodel import Session

from app.ai.pipeline import Deps
from app.api.deps import get_deps
from app.db import get_session
from app.models import NeedStatus, Segment
from app.schemas import MAX_ID, ErrorResponse, NeedSort, PortalNeedDetail, PortalNeedPage
from app.services import portal

router = APIRouter(prefix="/portal", tags=["portal"])


@router.get("/needs", response_model=PortalNeedPage, responses={422: {"model": ErrorResponse}},
            summary="Find needs (requester view: no scores, revenue or accounts)")  # fmt: skip
def list_needs(
    q: str | None = Query(None, max_length=200),
    status: NeedStatus | None = None,
    product_area: str | None = Query(None, max_length=100),
    segment: Segment | None = None,
    sort: NeedSort = "priority",
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    session: Session = Depends(get_session),
    deps: Deps = Depends(get_deps),
) -> dict[str, Any]:
    return portal.list_needs(session, q=q, status=status, product_area=product_area, segment=segment, sort=sort,
                             page=page, page_size=page_size, cfg=deps.priorities)  # fmt: skip


@router.get("/needs/{need_id}", response_model=PortalNeedDetail,
            responses={404: {"model": ErrorResponse}, 422: {"model": ErrorResponse}},
            summary="A need as a requester sees it, with the updates written to them")  # fmt: skip
def need(
    need_id: int = Path(ge=1, le=MAX_ID),
    requester_id: int | None = Query(None, ge=1, le=MAX_ID, description="Whose updates to include"),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    return portal.need(session, need_id, requester_id)
