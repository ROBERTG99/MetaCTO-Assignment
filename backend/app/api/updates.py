from typing import Annotated, Any

from fastapi import APIRouter, Depends, Path
from sqlmodel import Session

from app.api.triage import Decision
from app.db import get_session
from app.schemas import MAX_ID, DraftEdit, DraftOut, ErrorResponse, OutboxOut
from app.services import updates

router = APIRouter(tags=["updates"])
UpdateId = Annotated[int, Path(ge=1, le=MAX_ID)]
ERRORS: dict[int | str, dict[str, Any]] = {404: {"model": ErrorResponse}, 409: {"model": ErrorResponse},
                                           422: {"model": ErrorResponse}}  # fmt: skip


@router.patch("/updates/{update_id}", response_model=DraftOut, responses=ERRORS,
              summary="Edit a draft; the commitment check runs again on the new text")  # fmt: skip
def edit(update_id: UpdateId, body: DraftEdit, session: Session = Depends(get_session)) -> dict[str, Any]:
    return updates.edit(session, update_id, body.body, body.by)


@router.post("/updates/{update_id}/approve", response_model=DraftOut, responses=ERRORS,
             summary="Approve and send to the (simulated) outbox; 409 while commitments are flagged")  # fmt: skip
def approve(update_id: UpdateId, body: Decision, session: Session = Depends(get_session)) -> dict[str, Any]:
    return updates.approve(session, update_id, body.by)


@router.post(
    "/updates/{update_id}/discard", response_model=DraftOut, responses=ERRORS, summary="Discard a draft"
)
def discard(update_id: UpdateId, body: Decision, session: Session = Depends(get_session)) -> dict[str, Any]:
    return updates.discard(session, update_id, body.by)


@router.get("/outbox", response_model=list[OutboxOut], summary="The simulated outbox: approved messages only")
def outbox(session: Session = Depends(get_session)) -> list[dict[str, Any]]:
    return updates.outbox(session)
