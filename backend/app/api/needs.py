from fastapi import APIRouter, Depends, Path, Query, Response
from sqlmodel import Session

from app.db import get_session
from app.models import NeedStatus, Segment
from app.schemas import MAX_ID, ErrorResponse, NeedDetail, NeedPage, NeedSort, SupportCreate, SupportOut
from app.services import needs as service

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
    )


@router.get(
    "/needs/{need_id}",
    response_model=NeedDetail,
    responses={404: {"model": ErrorResponse}, 422: {"model": ErrorResponse}},
)
def get_need(need_id: int = NeedId, session: Session = Depends(get_session)) -> NeedDetail:
    return service.get_need(session, need_id)


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
