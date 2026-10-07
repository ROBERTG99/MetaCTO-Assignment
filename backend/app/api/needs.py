from typing import Annotated, Any

from fastapi import APIRouter, Depends, Path, Query, Request, Response
from sqlmodel import Session

from app.ai.pipeline import Deps
from app.api.deps import get_deps
from app.api.triage import Decision
from app.db import get_session
from app.limits import public_write
from app.models import NeedStatus, Segment
from app.schemas import (
    MAX_ID,
    ErrorResponse,
    NeedDetail,
    NeedPage,
    NeedSort,
    NeedUpdates,
    SimilarNeed,
    StatusChangeIn,
    StatusChangeOut,
    SupportCreate,
    SupportOut,
)
from app.services import needs as service
from app.services import triage, updates

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
    _limit: None = Depends(public_write),
) -> SupportOut:
    support, created = service.add_support(session, need_id, body)
    response.status_code = 201 if created else 200
    return support


@router.patch(
    "/needs/{need_id}/status",
    response_model=StatusChangeOut,
    responses={404: {"model": ErrorResponse}, 409: {"model": ErrorResponse}, 422: {"model": ErrorResponse}},
    summary="Change a need's status (a human product decision) and queue the stakeholder drafts",
    description="Saved at once; the worker then drafts a personal update per supporter and a CS note per "
    "account. Nothing is sent until a PM approves each draft. 409 for a merged need or the same status.",
)
def change_status(
    body: StatusChangeIn, need_id: int = NeedId, session: Session = Depends(get_session)
) -> dict[str, Any]:
    change = updates.change_status(session, need_id, body.status, body.reason, body.target_date, body.by)
    return updates.change_out(session, change)


@router.get(
    "/needs/{need_id}/updates",
    response_model=NeedUpdates,
    responses={404: {"model": ErrorResponse}, 422: {"model": ErrorResponse}},
    summary="Status changes with their drafted, approved and discarded stakeholder messages (PM view)",
)
def need_updates(need_id: int = NeedId, session: Session = Depends(get_session)) -> dict[str, Any]:
    return updates.list_for_need(session, need_id)


@router.post(
    "/needs/{need_id}/status-changes/{change_id}/redraft",
    response_model=StatusChangeOut,
    responses={404: {"model": ErrorResponse}, 409: {"model": ErrorResponse}, 422: {"model": ErrorResponse}},
    summary="Draft the stakeholder messages again after drafting failed (spends one model call)",
)
def redraft(
    body: Decision,
    change_id: Annotated[int, Path(ge=1, le=MAX_ID)],
    need_id: int = NeedId,
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    change = updates.redraft(session, need_id, change_id)
    return updates.change_out(session, change)
