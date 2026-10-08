from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.engine import Engine
from sqlmodel import SQLModel

from app.db import make_engine


def test_sqlite_runs_in_wal_mode_with_foreign_keys(engine: Engine) -> None:
    with engine.connect() as conn:
        assert conn.execute(text("PRAGMA journal_mode")).scalar() == "wal"
        assert conn.execute(text("PRAGMA foreign_keys")).scalar() == 1


def test_a_database_in_a_folder_that_does_not_exist_yet_can_be_opened(tmp_path: Path) -> None:
    """A fresh clone has no backend/data/ (it is gitignored): `make seed` must still work (drop_all connects first)."""
    target = tmp_path / "data" / "nested" / "distill.db"
    engine = make_engine(f"sqlite:///{target}")
    SQLModel.metadata.drop_all(engine)  # what load_seed does before anything creates a table
    assert target.exists()
    engine.dispose()


def test_an_in_memory_database_creates_no_folder(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    with make_engine("sqlite://").connect() as conn:
        assert conn.execute(text("select 1")).scalar() == 1
    assert list(tmp_path.iterdir()) == []
