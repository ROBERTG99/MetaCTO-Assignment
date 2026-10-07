from fastapi import APIRouter, Depends
from sqlmodel import Session, col, select

from app.db import get_session
from app.models import Account, Requester
from app.schemas import RequesterOut

router = APIRouter(tags=["requesters"])


@router.get(
    "/requesters",
    response_model=list[RequesterOut],
    summary="People the UI can act as (no auth, spec A3)",
)
def list_requesters(session: Session = Depends(get_session)) -> list[RequesterOut]:
    rows = session.exec(
        select(Requester, Account)
        .join(Account, isouter=True)
        .order_by(col(Requester.name), col(Requester.id))
    ).all()
    return [
        RequesterOut(
            id=p.id,
            name=p.name,
            role=p.role,
            account_id=p.account_id,
            account_name=a.name if a else None,
            segment=a.segment if a else None,
        )
        for p, a in rows
    ]
