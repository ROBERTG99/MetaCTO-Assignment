"""`make seed-live REFS=R22,R13,R07`: run a few seed requests through the live pipeline (paid; asks first).

The database is reset to the seed, the curated backlog is built from ground_truth.json (17 needs, their
requests linked), and only the chosen requests are left pending. The worker then processes them with
AI_MODE=live, and their AIRun rows are printed. Each request makes 2 calls (extract + adjudicate), plus at
most one repair or max_tokens retry per call.
"""

import argparse
import json
import os

from sqlmodel import Session, select

from app.config import get_settings
from app.db import get_engine
from app.models import AIRun, AISuggestion, Need, Request, RequestStatus
from seed.load import SEED_DIR, load_seed


def build_backlog(session: Session, keep_pending: set[str]) -> dict[str, int]:
    truth = json.loads((SEED_DIR / "ground_truth.json").read_text(encoding="utf-8"))
    refs = [r["ref"] for r in json.loads((SEED_DIR / "requests.json").read_text(encoding="utf-8"))]
    needs: dict[str, int] = {}
    for key, info in truth["needs"].items():
        need = Need(title=info["title"], problem=info["title"], persona=info["persona"],
                    product_area=info["product_area"], created_by="seed")  # fmt: skip
        session.add(need)
        session.flush()
        assert need.id is not None
        needs[key] = need.id
    rows = session.exec(select(Request).order_by(Request.id)).all()  # type: ignore[arg-type]
    for ref, r in zip(refs, rows, strict=True):  # loaded in file order
        if ref in keep_pending:
            continue
        gold = truth["requests"][ref]["need"]
        r.need_id = needs[gold] if gold else None
        r.status = RequestStatus.processed
        session.add(r)
    session.commit()
    return {ref: r.id for ref, r in zip(refs, rows, strict=True) if ref in keep_pending and r.id is not None}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--refs", required=True, help="comma-separated seed refs, e.g. R22,R13,R07")
    refs = {x.strip() for x in ap.parse_args().refs.split(",") if x.strip()}
    if get_settings().ai_mode != "live":
        raise SystemExit("AI_MODE must be live for seed-live")
    if not (get_settings().anthropic_api_key or os.environ.get("ANTHROPIC_AUTH_TOKEN")):
        print(
            "note: no ANTHROPIC_API_KEY in the environment or .env; the SDK will look for an `ant auth login` profile"
        )
    from app.ai.factory import build_deps
    from app.worker import Worker

    engine = get_engine()
    load_seed(engine)
    with Session(engine) as session:
        ids = build_backlog(session, refs)
    deps = build_deps(engine)
    with Session(engine) as session:
        deps.search.rebuild(session)
    worker = Worker(engine, deps)
    while worker.run_once():
        pass
    with Session(engine) as session:
        for ref, rid in sorted(ids.items()):
            r = session.get(Request, rid)
            assert r is not None
            sug = session.exec(select(AISuggestion).where(AISuggestion.request_id == rid)).all()
            need = session.get(Need, r.need_id) if r.need_id else None
            print(
                f"\n{ref} (request {rid}) {r.title!r}: status={r.status} need={need.title if need else None!r}"
            )
            print(
                f"  extraction: {r.need_statement!r} persona={r.persona} area={r.product_area} severity={r.severity_signal}"
            )
            for s in sug:
                print(
                    f"  suggestion: kind={s.kind} state={s.state} need={s.need_id} label={s.label} score={s.routing_score}"
                )
            if r.needs_review_reason:
                print(f"  needs_review: {r.needs_review_reason}")
        print("\nAIRun rows:")
        total = 0.0
        for run in session.exec(select(AIRun).order_by(AIRun.id)).all():  # type: ignore[arg-type]
            total += run.cost_usd
            print(f"  #{run.id} request={run.request_id} {run.step:<10} {run.model:<18} {run.prompt_version:<16} "
                  f"in={run.input_tokens:>5} out={run.output_tokens:>5} ${run.cost_usd:.5f} {run.latency_ms:>6} ms {run.outcome}"
                  + (f" ({run.error})" if run.error else ""))  # fmt: skip
        print(f"  total ${total:.4f}")


if __name__ == "__main__":
    main()
