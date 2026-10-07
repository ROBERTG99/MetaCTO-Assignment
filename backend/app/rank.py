"""Print the backlog ranking from the local database: `make rank` (PRIORITIES=path to try another config).

Nothing is written. Every number comes from app/scoring.py at read time, so a different priorities file
re-ranks the same data with no code change, no prompt change and no model call.
"""

import argparse
from pathlib import Path

from sqlmodel import Session, col, select

from app.ai.factory import CONFIG
from app.db import get_engine
from app.models import Need
from app.scoring import load_priorities, rank_key
from app.services.priority import UNDECIDED, breakdowns


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--config", type=Path, default=CONFIG / "priorities.yaml")
    ap.add_argument("--top", type=int, default=12)
    args = ap.parse_args(argv)
    cfg = load_priorities(args.config)
    with Session(get_engine()) as s:
        needs = list(s.exec(select(Need).where(col(Need.status).in_(UNDECIDED))).all())
        bds = breakdowns(s, needs, cfg)
    rows = sorted(needs, key=lambda n: rank_key(bds[n.id].priority, bds[n.id].demand.accounts, n.id or 0))  # type: ignore[index]
    print(f"{args.config} · weights D {cfg.w_demand} S {cfg.w_strategic} U {cfg.w_urgency}")
    print(
        f"{'#':>2} {'need':>4} {'priority':>8} {'D':>5} {'S':>5} {'U':>5}  {'quadrant':<20} {'owner':<14} title"
    )
    for i, n in enumerate(rows[: args.top], 1):
        b = bds[n.id]  # type: ignore[index]
        s_ = "  -  " if b.strategic.value is None else f"{b.strategic.value:5.2f}"
        print(f"{i:>2} {n.id:>4} {b.priority:8.1f} {b.demand.value:5.2f} {s_} {b.urgency.value:5.2f}  "
              f"{b.quadrant or 'not rated':<20} {b.owner:<14} {n.title[:60]}")  # fmt: skip
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
