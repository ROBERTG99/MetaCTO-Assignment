from fastapi import APIRouter, Depends
from sqlmodel import Session

from app.db import get_session
from app.schemas import ErrorResponse, RequestCreate, RequestOut
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
