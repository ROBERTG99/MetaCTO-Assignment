"""Submitting a request: saved as pending for the worker, before any AI work (ADR 0007)."""

from sqlmodel import Session

from app.errors import AppError
from app.models import Account, Request, Requester, RequestSource, RequestStatus
from app.schemas import RequestCreate


def get_requester(session: Session, requester_id: int) -> Requester:
    requester = session.get(Requester, requester_id)
    if requester is None:
        raise AppError(
            422,
            "unknown_requester",
            f"Requester {requester_id} does not exist",
            [{"field": "requester_id", "issue": "unknown requester"}],
        )
    return requester


def resolve_account(session: Session, requester: Requester, body: RequestCreate) -> int | None:
    """The customer a request is for: the requester's own account, or the one staff name on its behalf."""

    def fail(code: str, message: str) -> AppError:
        return AppError(422, code, message, [{"field": "account_id", "issue": message}])

    if body.account_id is not None and session.get(Account, body.account_id) is None:
        raise fail("unknown_account", f"Account {body.account_id} does not exist")
    if requester.account_id is not None:
        if body.account_id not in (None, requester.account_id):
            raise fail("account_mismatch", "A customer can only submit for their own account")
        return requester.account_id
    if body.account_id is None and body.source != RequestSource.internal:
        raise fail("account_required", f"Staff must name the customer account for a {body.source} request")
    return body.account_id


def create_request(session: Session, body: RequestCreate) -> Request:
    requester = get_requester(session, body.requester_id)
    request = Request(
        requester_id=body.requester_id,
        account_id=resolve_account(session, requester, body),
        source=body.source,
        title=body.title,
        description=body.description,
        status=RequestStatus.pending,
    )
    session.add(request)
    session.commit()
    session.refresh(request)
    return request
