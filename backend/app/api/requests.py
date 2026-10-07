from typing import Any

from fastapi import APIRouter, Depends, Query
from sqlmodel import Session

from app.db import get_session
from app.schemas import MAX_ID, ErrorResponse, MyRequest, RequestCreate, RequestOut
from app.services import requests as service

router = APIRouter(tags=["requests"])


@router.post(
    "/requests",
    status_code=201,
    response_model=RequestOut,
    responses={422: {"model": ErrorResponse}},
    summary="Submit a feature request",
    description="Saves the request as `pending` and returns at once; the intake workflow runs later.",
)
def create_request(body: RequestCreate, session: Session = Depends(get_session)) -> RequestOut:
    return RequestOut.model_validate(service.create_request(session, body))


@router.get(
    "/requests",
    response_model=list[MyRequest],
    responses={422: {"model": ErrorResponse}},
    summary="A requester's own requests, newest first, with their status and need",
)
def my_requests(
    requester_id: int = Query(ge=1, le=MAX_ID), session: Session = Depends(get_session)
) -> list[dict[str, Any]]:
    return service.list_mine(session, requester_id)
