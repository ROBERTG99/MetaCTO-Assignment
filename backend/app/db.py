"""SQLite engine in WAL mode (ADR 0005) and the session dependency."""

import os
from collections.abc import Iterator
from typing import Any

from fastapi import Request
from sqlalchemy import event
from sqlalchemy.engine import Engine, make_url
from sqlmodel import Session, SQLModel, create_engine

from app.config import get_settings


def make_engine(url: str) -> Engine:
    # A fresh clone has no backend/data/ (gitignored); SQLite can create the file but not its folder.
    folder = os.path.dirname(make_url(url).database or "")
    if folder:
        os.makedirs(folder, exist_ok=True)
    engine = create_engine(url, connect_args={"check_same_thread": False})

    @event.listens_for(engine, "connect")
    def _sqlite_pragmas(dbapi_connection: Any, _record: Any) -> None:
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA busy_timeout=5000")
        cursor.close()

    return engine


_engine: Engine | None = None


def get_engine() -> Engine:
    global _engine
    if _engine is None:
        _engine = make_engine(get_settings().database_url)
    return _engine


def create_tables(engine: Engine) -> None:
    import app.models  # noqa: F401  (registers the tables)

    SQLModel.metadata.create_all(engine)


def get_session(request: Request) -> Iterator[Session]:
    with Session(request.app.state.engine) as session:
        yield session
