from typing import Annotated, Any

from fastapi import APIRouter, Depends, Path, Request
from pydantic import BaseModel, StringConstraints
from sqlmodel import Session

from app.db import get_session
from app.schemas import MAX_ID, DecisionResult, ErrorResponse, TriageList, UnlinkResult
from app.services import triage as service

router = APIRouter(tags=["triage"])
SuggestionId = Annotated[int, Path(ge=1, le=MAX_ID)]
RequestId = Annotated[int, Path(ge=1, le=MAX_ID)]
ERRORS: dict[int | str, dict[str, Any]] = {
    404: {"model": ErrorResponse},
    409: {"model": ErrorResponse},
    422: {"model": ErrorResponse},
}


class Decision(BaseModel):
    """Who decided. There is no auth yet (spec A3), so the PM names themselves."""

    by: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]


@router.get(
    "/triage",
    response_model=TriageList,
    summary="The PM inbox: suggestions, claim disputes, the audit sample and failures",
)
def list_triage(request: Request, session: Session = Depends(get_session)) -> dict[str, Any]:
    return service.list_triage(session, request.app.state.deps)


@router.post(
    "/triage/{suggestion_id}/accept",
    response_model=DecisionResult,
    responses=ERRORS,
    summary="Accept a suggestion, confirm a claim, or mark an audit correct",
)
def accept(
    suggestion_id: SuggestionId, body: Decision, request: Request, session: Session = Depends(get_session)
) -> dict[str, Any]:
    return service.accept(session, suggestion_id, body.by, request.app.state.deps)


@router.post(
    "/triage/{suggestion_id}/reject",
    response_model=DecisionResult,
    responses=ERRORS,
    summary="Reject a suggestion or claim, or mark an audit a false merge",
)
def reject(
    suggestion_id: SuggestionId, body: Decision, request: Request, session: Session = Depends(get_session)
) -> dict[str, Any]:
    return service.reject(session, suggestion_id, body.by, request.app.state.deps)


@router.post(
    "/requests/{request_id}/unlink",
    response_model=UnlinkResult,
    responses=ERRORS,
    summary="Undo a link: the request becomes its own need",
)
def unlink(
    request_id: RequestId, body: Decision, request: Request, session: Session = Depends(get_session)
) -> dict[str, Any]:
    return service.unlink(session, request_id, body.by, request.app.state.deps)
