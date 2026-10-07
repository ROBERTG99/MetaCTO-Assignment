"""Shared fixtures: a throwaway SQLite file (WAL needs a file) per test, and small factories."""

from collections.abc import Iterator
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.engine import Engine
from sqlmodel import Session

from app.db import create_tables, make_engine
from app.main import create_app
from app.models import Account, Need, Request, Requester, RequestSource, Segment, Support, SupportLinkStatus


@pytest.fixture
def engine(tmp_path: Path) -> Iterator[Engine]:
    eng = make_engine(f"sqlite:///{tmp_path / 'test.db'}")
    create_tables(eng)
    yield eng
    eng.dispose()


@pytest.fixture
def client(engine: Engine) -> Iterator[TestClient]:
    with TestClient(create_app(engine)) as c:
        yield c


@pytest.fixture
def db(engine: Engine) -> Iterator[Session]:
    with Session(engine, expire_on_commit=False) as session:
        yield session


class Factory:
    def __init__(self, session: Session) -> None:
        self.s = session

    def _save(self, obj: Any) -> Any:
        self.s.add(obj)
        self.s.commit()
        self.s.refresh(obj)
        return obj

    def account(self, name: str = "Acme", segment: Segment = Segment.mid_market, **kw: Any) -> Account:
        kw.setdefault("arr", 50_000)
        kw.setdefault("renewal_date", date(2027, 3, 1))
        return self._save(Account(name=name, segment=segment, **kw))  # type: ignore[no-any-return]

    def requester(
        self, account: Account | None = None, name: str = "Dana", role: str = "Analyst"
    ) -> Requester:
        return self._save(  # type: ignore[no-any-return]
            Requester(name=name, role=role, account_id=account.id if account else None)
        )

    def need(self, title: str = "Finance needs month-end data in Excel", **kw: Any) -> Need:
        kw.setdefault("problem", title)
        return self._save(Need(title=title, **kw))  # type: ignore[no-any-return]

    def request(
        self,
        requester: Requester,
        need: Need | None = None,
        title: str = "Export to Excel",
        created_at: datetime | None = None,
        **kw: Any,
    ) -> Request:
        assert requester.id is not None
        kw.setdefault("source", RequestSource.portal)
        kw.setdefault("account_id", requester.account_id)
        if created_at is not None:
            kw["created_at"] = created_at
        return self._save(  # type: ignore[no-any-return]
            Request(requester_id=requester.id, title=title, need_id=need.id if need else None, **kw)
        )

    def support(self, need: Need, requester: Requester, status: SupportLinkStatus, **kw: Any) -> Support:
        assert need.id is not None and requester.id is not None
        return self._save(  # type: ignore[no-any-return]
            Support(need_id=need.id, requester_id=requester.id, link_status=status, **kw)
        )


@pytest.fixture
def make(db: Session) -> Factory:
    return Factory(db)


def days_ago(n: int) -> datetime:
    return datetime(2026, 10, 1, tzinfo=UTC) - timedelta(days=n)


def assert_error(body: dict[str, Any], code: str) -> None:
    """Our error shape: {"error": {"code": str, "message": str, "details": [...]}}."""
    assert set(body) == {"error"}, body
    assert body["error"]["code"] == code, body
    assert isinstance(body["error"]["message"], str) and body["error"]["message"], body
