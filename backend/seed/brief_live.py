"""`make brief-live`: one live decision brief for one seeded need (paid; settings ask first).

The database (DATABASE_URL, data/live.db from the Makefile, never the dev database) is reset to the seed, a
brief is queued for the first live need whose title contains --need, and the worker runs exactly that job:
the overlap agent on FAST_MODEL (at most 8 tool calls, 9 turns) and the brief on SMART_MODEL (1 call, plus 1
repair round if a claim fails). The brief is written as markdown to --out, and every call's tokens (cache
reads included), cost and latency are printed from ai_runs.
"""

import argparse
import os
from pathlib import Path

from sqlmodel import Session, col, func, select

from app.config import get_settings
from app.db import get_engine
from app.models import (
    Brief,
    Need,
    NeedStatus,
    NeedStatusChange,
    Request,
    RequestStatus,
    Support,
    SupportLinkStatus,
)
from app.services.briefs import brief_out, request_brief, to_markdown
from seed.load import load_seed


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--need", required=True, help="text in the need's title, e.g. 'SAML SSO with Okta'")
    ap.add_argument("--out", required=True, type=Path, help="markdown file to write")
    args = ap.parse_args()
    settings = get_settings()
    if settings.ai_mode != "live":
        raise SystemExit("AI_MODE must be live for brief-live")
    if not (settings.anthropic_api_key or os.environ.get("ANTHROPIC_AUTH_TOKEN")):
        print(
            "note: no ANTHROPIC_API_KEY in the environment or .env; the SDK will look for an `ant auth login` profile"
        )
    from app.ai.factory import build_deps
    from app.worker import Worker

    engine = get_engine()
    load_seed(engine, snapshot=True)  # the recorded backlog: processed requests, no pending work
    deps = build_deps(engine)
    with Session(engine) as session:
        queued = {
            "pending requests": session.exec(select(func.count()).select_from(Request).where(
                Request.status == RequestStatus.pending)).one(),
            "claims to check": session.exec(select(func.count()).select_from(Support).where(
                Support.link_status == SupportLinkStatus.claimed)).one(),
            "drafts to write": session.exec(select(func.count()).select_from(NeedStatusChange).where(
                NeedStatusChange.drafts_status == "pending")).one(),
            "fit ratings due": session.exec(select(func.count()).select_from(Need).where(Need.fit_status == "pending")).one(),
        }  # fmt: skip
        if any(queued.values()):  # the worker would spend on these before the brief: stop before any call
            raise SystemExit(f"other jobs are queued, refusing to run: {queued}")
        deps.search.rebuild(session)
        need = session.exec(
            select(Need).where(col(Need.title).contains(args.need), Need.status != NeedStatus.merged)
        ).first()
        if need is None or need.id is None:
            raise SystemExit(f"no live need whose title contains {args.need!r}")
        title, brief_id = need.title, request_brief(session, need.id, "robert (live validation)").id
    done = Worker(engine, deps).run_once()
    if done != f"brief:{brief_id}":
        raise SystemExit(f"expected the worker to run brief:{brief_id}, it ran {done!r}")
    with Session(engine) as session:
        row = session.get(Brief, brief_id)
        assert row is not None
        out = brief_out(session, row)
    if out["status"] != "ready":
        raise SystemExit(f"brief {brief_id} is {out['status']}: {out['error']}")
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(to_markdown(out, title), encoding="utf-8")
    c = out["content"]
    print(f"brief {brief_id} for {title!r}: written to {args.out}")
    print(f"verification: {c['flagged']} of {len(c['checks'])} claims flagged; repaired={c['repaired']}")
    print(
        f"overlap agent: {c['related']['status']}, {c['related']['tool_calls']} of {c['related']['cap']} tool calls"
    )
    for x in out["calls"]:
        print(
            f"  run {x['id']} {x['step']} {x['model']}: input={x['input_tokens']} cache_write={x['cache_write_tokens']} "
            f"cache_read_input_tokens={x['cache_read_tokens']} output={x['output_tokens']} "
            f"cost=${x['cost_usd']:.4f} latency={x['latency_ms']} ms outcome={x['outcome']}"
        )
    print(f"total: {len(out['calls'])} calls, ${sum(x['cost_usd'] for x in out['calls']):.4f}")


if __name__ == "__main__":
    main()
