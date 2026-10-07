"""Load the raw Brightboard seed (accounts, requesters, requests) into a fresh database.

Only raw data is loaded: requests arrive as `pending`, with no needs, so the intake workflow has real
work to do. ground_truth.json is for tests and evals and is never loaded. Run: `make seed`.
"""

import json
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

from sqlalchemy.engine import Engine
from sqlmodel import Session, SQLModel

from app.db import create_tables, get_engine
from app.models import Account, Request, Requester, RequestSource, RequestStatus, Segment

SEED_DIR = Path(__file__).resolve().parent
START = datetime(2026, 7, 1, 9, 0, tzinfo=UTC)


def _read(name: str) -> Any:
    return json.loads((SEED_DIR / name).read_text(encoding="utf-8"))


def load_seed(engine: Engine) -> dict[str, int]:
    """Drop and recreate every table, then insert the seed. Returns the row counts."""
    import app.models  # noqa: F401  (registers the tables)

    SQLModel.metadata.drop_all(engine)
    create_tables(engine)
    with Session(engine) as session:
        accounts: dict[str, Account] = {}
        for a in _read("accounts.json"):
            accounts[a["ref"]] = Account(
                name=a["name"],
                segment=Segment(a["segment"]),
                arr=a["arr"],
                renewal_date=date.fromisoformat(a["renewal_date"]) if a.get("renewal_date") else None,
                is_prospect=a.get("is_prospect", False),
                pipeline_value=a.get("pipeline_value"),
            )
        session.add_all(accounts.values())
        session.flush()
        people: dict[str, Requester] = {}
        for p in _read("requesters.json"):
            account = accounts[p["account"]] if p["account"] else None
            people[p["ref"]] = Requester(
                name=p["name"], role=p["role"], account_id=account.id if account else None
            )
        session.add_all(people.values())
        session.flush()
        requests = []
        for r in _read("requests.json"):
            requester = people[r["requester"]]
            assert requester.id is not None
            account_id = accounts[r["account"]].id if r["account"] else requester.account_id
            requests.append(
                Request(
                    requester_id=requester.id,
                    account_id=account_id,
                    source=RequestSource(r["source"]),
                    title=r["title"],
                    description=r["description"],
                    status=RequestStatus.pending,
                    created_at=START + timedelta(days=r["day"], minutes=7 * int(r["ref"][1:])),
                )
            )
        session.add_all(requests)
        session.commit()
        return {"accounts": len(accounts), "requesters": len(people), "requests": len(requests)}


def main() -> None:
    engine = get_engine()
    counts = load_seed(engine)
    print(
        f"Seeded {engine.url}: {counts['accounts']} accounts, {counts['requesters']} requesters, "
        f"{counts['requests']} pending requests, 0 needs"
    )


if __name__ == "__main__":
    main()
