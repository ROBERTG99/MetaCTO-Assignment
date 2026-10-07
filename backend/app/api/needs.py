from typing import Any

from fastapi import APIRouter, Depends, Path, Query, Request, Response
from sqlmodel import Session

from app.ai.pipeline import Deps
from app.api.deps import get_deps
from app.db import get_session
from app.models import NeedStatus, Segment
from app.schemas import (
    MAX_ID,
    ErrorResponse,
    NeedDetail,
    NeedPage,
    NeedSort,
    NeedStatusUpdate,
    SimilarNeed,
    SupportCreate,
    SupportOut,
)
from app.services import needs as service
from app.services import triage

router = APIRouter(tags=["needs"])
NeedId = Path(ge=1, le=MAX_ID)


@router.get(
    "/needs", response_model=NeedPage, responses={422: {"model": ErrorResponse}}, summary="Find needs"
)
def list_needs(
    q: str | None = Query(None, max_length=200, description="Text in the need or its member requests"),
    status: NeedStatus | None = None,
    product_area: str | None = Query(None, max_length=100),
    segment: Segment | None = Query(None, description="Needs with a request or confirmed support from it"),
    sort: NeedSort = "priority",
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    session: Session = Depends(get_session),
    deps: Deps = Depends(get_deps),
) -> NeedPage:
    return service.list_needs(
        session,
        q=q,
        status=status,
        product_area=product_area,
        segment=segment,
        sort=sort,
        page=page,
        page_size=page_size,
        cfg=deps.priorities,
    )


@router.get(
    "/needs/similar",
    response_model=list[SimilarNeed],
    summary="Needs similar to what the requester is typing (embeddings only)",
)
def similar_needs(
    request: Request,
    q: str = Query(min_length=3, max_length=500),
    session: Session = Depends(get_session),
) -> list[dict[str, Any]]:
    return triage.similar(session, q, request.app.state.deps)


@router.get(
    "/needs/{need_id}",
    response_model=NeedDetail,
    responses={404: {"model": ErrorResponse}, 422: {"model": ErrorResponse}},
)
def get_need(
    need_id: int = NeedId, session: Session = Depends(get_session), deps: Deps = Depends(get_deps)
) -> NeedDetail:
    return service.get_need(session, need_id, deps.priorities)


@router.post(
    "/needs/{need_id}/support",
    response_model=SupportOut,
    status_code=201,
    responses={
        200: {"model": SupportOut},
        404: {"model": ErrorResponse},
        409: {"model": ErrorResponse},
        422: {"model": ErrorResponse},
    },
    summary="Add support (a requester claim)",
    description="201 the first time, 200 on a repeat by the same requester. Not counted until confirmed. "
    "409 if the need was merged into another one.",
)
def add_support(
    body: SupportCreate,
    response: Response,
    need_id: int = NeedId,
    session: Session = Depends(get_session),
) -> SupportOut:
    support, created = service.add_support(session, need_id, body)
    response.status_code = 201 if created else 200
    return support


@router.patch(
    "/needs/{need_id}",
    response_model=NeedDetail,
    responses={404: {"model": ErrorResponse}, 409: {"model": ErrorResponse}, 422: {"model": ErrorResponse}},
    summary="Set a need's status (a human product decision)",
    description="Appends to the status history, shown in the audit trail. 409 for a merged need.",
)
def set_status(
    body: NeedStatusUpdate,
    need_id: int = NeedId,
    session: Session = Depends(get_session),
    deps: Deps = Depends(get_deps),
) -> NeedDetail:
    from app.services import need_detail

    need_detail.set_status(session, need_id, body.status, body.by)
    return service.get_need(session, need_id, deps.priorities)
