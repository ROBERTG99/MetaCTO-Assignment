"""Strategic-fit eval and the seed's recorded ratings. One set of calls serves both.

    make eval STEP=fit     paid (settings ask first): rate the seeded needs and the labelled cases
    make eval-fit-report   free: rebuild the report and backend/seed/fit_snapshot.json from the cache

The labelled cases (datasets/strategic_fit.jsonl) are 10 of the seeded needs, with the exact text the app
sends (fit_texts), so their calls are the seed's calls. Every reply is cached in evals/results/fit_cache.jsonl
(separate from llm_cache.jsonl, which the routing evals and the seed snapshot pin by hash).

Metrics, per (need, goal) pair, human label vs model: agreement within one point (what was asked for), exact
agreement and mean absolute error; per need, Spearman correlation of S. Within one point is lenient on a 0-3
scale: a constant 1 or 2 is within one of three of the four values, so the constant baselines are reported too,
with a no-LLM baseline (embedding similarity to each goal, ranked into 0-3). Pairs from one need aren't
independent, so the Wilson intervals on pairs are optimistic.
"""

import argparse
import hashlib
import json
import math
import os
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import yaml
from app.ai.embeddings import FastEmbedder
from app.ai.gateway import AnthropicClient, Gateway, LLMClient, StepConfig, TerminalError, TransientError
from app.ai.pipeline import fit_texts, verify_quotes
from app.ai.schemas import StrategicFit
from app.models import AIRun, Need
from app.scoring import Goal, PrioritiesConfig, goals_digest, load_priorities, strategic_fit
from pydantic import BaseModel, ConfigDict, Field, field_validator

from evals.dataset import DATASETS
from evals.llm import CONFIG, RESULTS, ROOT, SEED, CachingClient, _retrying
from evals.metrics import Rate, percentile
from evals.snapshot import MissingFromCache, NoNetwork

DATASET = DATASETS / "strategic_fit.jsonl"
CACHE = RESULTS / "fit_cache.jsonl"
SEED_OUT = SEED / "fit_snapshot.json"
RESULT_MD = RESULTS / "strategic_fit.md"
PROMPT = "strategic_fit_v1"
CASE_IDS = (1, 2, 3, 4, 5, 7, 8, 10, 19, 22)  # seeded need ids picked for labelling (see make_dataset)


# --- dataset --------------------------------------------------------------------------------------------


class FitNeedIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str
    problem: str
    persona: str | None
    job_to_be_done: str | None


class FitCase(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(pattern=r"^F[0-9]{2}$")
    need: FitNeedIn
    requests: list[str]
    expected: dict[str, int | None]
    rationale: str = ""
    author: str
    reviewed_by_human: bool

    @field_validator("expected")
    @classmethod
    def _ratings_in_range(cls, v: dict[str, int | None]) -> dict[str, int | None]:
        bad = {k: r for k, r in v.items() if r is not None and not 0 <= r <= 3}
        if bad:
            raise ValueError(f"ratings are 0-3: {bad}")
        return v


def load_fit_cases(path: Path, goals: tuple[str, ...], require_labels: bool = True) -> list[FitCase]:
    cases = [
        FitCase.model_validate_json(line) for line in path.read_text(encoding="utf-8").splitlines() if line
    ]
    for c in cases:
        if set(c.expected) != set(goals):
            raise ValueError(f"{c.id}: expected must rate exactly these goals: {', '.join(goals)}")
    if require_labels:
        missing = [
            c.id for c in cases if not c.reviewed_by_human or any(v is None for v in c.expected.values())
        ]
        if missing:
            raise ValueError(f"not rated or not reviewed by a human yet: {', '.join(missing)}")
    return cases


# --- metrics --------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Agreement:
    within_one: Rate
    exact: Rate
    mae: float


def agreement(pairs: list[tuple[int, int]]) -> Agreement:
    """(human, model) ratings on the 0-3 scale."""
    diffs = [abs(h - m) for h, m in pairs]
    n = len(diffs)
    return Agreement(
        Rate(sum(d <= 1 for d in diffs), n), Rate(sum(d == 0 for d in diffs), n), sum(diffs) / n if n else 0.0
    )


def _ranks(xs: list[float]) -> list[float]:
    order = sorted(range(len(xs)), key=lambda i: xs[i])
    ranks = [0.0] * len(xs)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and xs[order[j + 1]] == xs[order[i]]:
            j += 1
        for k in range(i, j + 1):
            ranks[order[k]] = (i + j) / 2 + 1
        i = j + 1
    return ranks


def spearman(xs: list[float], ys: list[float]) -> float | None:
    """Rank correlation, ties averaged. None when either side has no variance."""
    rx, ry = _ranks(xs), _ranks(ys)
    mx, my = sum(rx) / len(rx), sum(ry) / len(ry)
    cov = sum((a - mx) * (b - my) for a, b in zip(rx, ry, strict=True))
    vx, vy = sum((a - mx) ** 2 for a in rx), sum((b - my) ** 2 for b in ry)
    return cov / math.sqrt(vx * vy) if vx and vy else None


def rank_buckets(scores: dict[str, float]) -> dict[str, int]:
    """Spread scores over 0-3 by rank (lowest quarter 0, highest 3); ties broken by key."""
    order = sorted(scores, key=lambda k: (scores[k], k))
    return {k: min(3, i * 4 // len(order)) for i, k in enumerate(order)}


def embedding_baseline(
    cases: list[FitCase], goals: tuple[Goal, ...], embedder: Any
) -> dict[str, dict[str, int]]:
    """No LLM: cosine similarity between the need's text and each goal's description, ranked into 0-3 per goal."""
    need_vecs = embedder.embed([" ".join([c.need.title, c.need.problem, *c.requests]) for c in cases])
    goal_vecs = embedder.embed([f"{g.title}. {g.description}" for g in goals])
    sims = np.asarray(need_vecs) @ np.asarray(goal_vecs).T
    out: dict[str, dict[str, int]] = {c.id: {} for c in cases}
    for j, g in enumerate(goals):
        for cid, r in rank_buckets({c.id: float(sims[i, j]) for i, c in enumerate(cases)}).items():
            out[cid][g.key] = r
    return out


# --- calls ----------------------------------------------------------------------------------------------


@dataclass
class Rated:
    output: StrategicFit
    runs: list[AIRun]
    latency_ms: float


def fit_model(cfg: PrioritiesConfig) -> str:
    """The model the app calls for this step: the config alias (fast/smart) through settings, as factory.py."""
    from app.config import get_settings

    settings = get_settings()
    return {"fast": settings.fast_model, "smart": settings.smart_model}[cfg.fit_model]


def _gateway(client: LLMClient, runs: list[AIRun], model: str) -> Gateway:
    prices = yaml.safe_load((CONFIG / "prices.yaml").read_text(encoding="utf-8"))

    def record(run: AIRun) -> int:
        runs.append(run)
        return len(runs)

    return Gateway(
        client=client, steps={"strategic_fit": StepConfig(model, 1500)}, prices=prices, record=record
    )


def seeded_needs() -> list[tuple[int, FitNeedIn, list[str]]]:
    """The needs `make seed` creates, with the text the app would send for each (pipeline.fit_texts)."""
    from app.db import make_engine
    from seed.load import load_seed
    from sqlmodel import Session, select

    with tempfile.TemporaryDirectory() as tmp:
        engine = make_engine(f"sqlite:///{Path(tmp) / 'seed.db'}")
        load_seed(engine, snapshot=True, fit=False)  # the needs and texts, never the ratings being rebuilt
        with Session(engine) as s:
            out = [
                (
                    n.id,
                    FitNeedIn(
                        title=n.title,
                        problem=n.problem or n.title,
                        persona=n.persona,
                        job_to_be_done=n.job_to_be_done,
                    ),
                    fit_texts(s, n.id),
                )
                for n in s.exec(select(Need).order_by(Need.id)).all()  # type: ignore[arg-type]
                if n.id is not None
            ]
        engine.dispose()
    return out


def rate_all(
    items: list[tuple[str, FitNeedIn, list[str]]], cfg: PrioritiesConfig, paid: bool
) -> tuple[dict[str, Rated], list[str], dict[str, str]]:
    """Rate every item. Returns the ratings, the cache misses (free runs) and the failures per item: a refusal,
    output that failed validation twice, or a provider error that outlasted the retries. A failure is reported
    and counts against the model; it never aborts the run."""
    inner: LLMClient
    if paid:
        from app.config import get_settings

        settings = get_settings()
        key = settings.anthropic_api_key.get_secret_value() if settings.anthropic_api_key else None
        inner = AnthropicClient(60.0, 2, api_key=key)
    else:
        inner = NoNetwork()
    client = CachingClient(inner, CACHE)
    model = fit_model(cfg)
    rated: dict[str, Rated] = {}
    misses: list[str] = []
    failed: dict[str, str] = {}
    for key, need, texts in items:
        runs: list[AIRun] = []
        gw = _gateway(client, runs, model)
        before = len(client.latencies())

        def call(gw: Gateway = gw, need: FitNeedIn = need, texts: list[str] = texts) -> Any:
            return gw.rate_fit(
                title=need.title,
                problem=need.problem,
                persona=need.persona,
                job_to_be_done=need.job_to_be_done,
                requests=texts,
                goals=cfg.goals,
            )

        try:
            out, _ = _retrying(call)
        except MissingFromCache:
            misses.append(f"strategic_fit for {key}: {need.title[:70]}")
            continue
        except (TerminalError, TransientError) as exc:
            failed[key] = str(exc)[:200]
            continue
        rated[key] = Rated(out, runs, sum(client.latencies()[before:]))
    return rated, misses, failed


# --- outputs --------------------------------------------------------------------------------------------


def seed_snapshot(
    needs: list[tuple[int, FitNeedIn, list[str]]],
    rated: dict[str, Rated],
    failed: dict[str, str],
    cfg: PrioritiesConfig,
) -> dict[str, Any]:
    """Needs whose rating failed are left out (the app shows them unrated) and listed under "failed"."""
    return {
        "about": "Recorded strategic_fit_v1 ratings (Haiku 4.5) for the needs `make seed` creates, one rating per "
        "need over its final member requests. Built by `make eval-fit-report` from evals/results/fit_cache.jsonl.",
        "prompt": PROMPT,
        "model": fit_model(cfg),
        "goals_digest": goals_digest(cfg.goals),
        "cache_sha256": hashlib.sha256(CACHE.read_bytes()).hexdigest() if CACHE.exists() else None,
        "needs": {
            need.title: {
                "ratings": [r.model_dump() for r in rated[f"seed:{nid}"].output.ratings],
                "runs": [
                    {
                        "step": r.step,
                        "model": r.model,
                        "prompt_version": r.prompt_version,
                        "input_tokens": r.input_tokens,
                        "output_tokens": r.output_tokens,
                        "cost_usd": r.cost_usd,
                        "latency_ms": int(rated[f"seed:{nid}"].latency_ms / len(rated[f"seed:{nid}"].runs)),
                        "outcome": r.outcome,
                    }
                    for r in rated[f"seed:{nid}"].runs
                ],
            }
            for nid, need, _ in needs
            if f"seed:{nid}" in rated
        },
        "failed": {need.title: failed[f"seed:{nid}"] for nid, need, _ in needs if f"seed:{nid}" in failed},
    }


def _pct(r: Rate) -> str:
    lo, hi = r.interval
    return f"{r.k}/{r.n} = {100 * (r.value or 0):.0f}% ({100 * lo:.0f}-{100 * hi:.0f})"


def report(
    cases: list[FitCase],
    rated: dict[str, Rated],
    failed: dict[str, str],
    cfg: PrioritiesConfig,
    embedder: Any,
) -> str:
    """A case whose rating failed counts as a miss on every goal for the model (within one and exact), and is
    left out of its MAE and Spearman, which need a rating."""
    keys = tuple(g.key for g in cfg.goals)
    lost = [c for c in cases if f"case:{c.id}" in failed]
    cases_all, cases = cases, [c for c in cases if f"case:{c.id}" not in failed]
    model: dict[str, dict[str, int]] = {
        c.id: {r.goal: int(r.rating) for r in rated[f"case:{c.id}"].output.ratings} for c in cases
    }
    human = {c.id: {g: int(c.expected[g] or 0) for g in keys} for c in cases_all}
    methods: dict[str, dict[str, dict[str, int]]] = {
        "Haiku 4.5 (strategic_fit_v1)": model,
        "Constant 1 (no model)": {c.id: dict.fromkeys(keys, 1) for c in cases_all},
        "Constant 2 (no model)": {c.id: dict.fromkeys(keys, 2) for c in cases_all},
        "Embedding rank buckets (no LLM)": embedding_baseline(cases_all, cfg.goals, embedder),
    }

    def s_of(r: dict[str, int]) -> float:
        return strategic_fit(r, cfg).value or 0.0

    lines = [
        "| Method | Within 1 point | Exact | MAE | Spearman of S over needs |",
        "|---|---|---|---|---|",
    ]
    for name, pred in methods.items():
        subset = cases if pred is model else cases_all
        a = agreement([(human[c.id][g], pred[c.id][g]) for c in subset for g in keys])
        if pred is model and lost:
            extra = len(lost) * len(keys)
            a = Agreement(
                Rate(a.within_one.k, a.within_one.n + extra), Rate(a.exact.k, a.exact.n + extra), a.mae
            )
        rho = spearman([s_of(human[c.id]) for c in subset], [s_of(pred[c.id]) for c in subset])
        lines.append(
            f"| {name} | {_pct(a.within_one)} | {_pct(a.exact)} | {a.mae:.2f} | "
            f"{'n/a' if rho is None else f'{rho:.2f}'} |"
        )
    lines += ["", "Per goal, Haiku 4.5:", "", "| Goal | Within 1 point | Exact | MAE |", "|---|---|---|---|"]
    for g in keys:
        a = agreement([(human[c.id][g], model[c.id][g]) for c in cases])
        lines.append(f"| {g} | {_pct(a.within_one)} | {_pct(a.exact)} | {a.mae:.2f} |")
    lines += [
        "",
        "Per need (human / model; S with the current goal weights; strategic side is S ≥ "
        f"{cfg.strategic_cut}):",
        "",
        "| Case | Need | " + " | ".join(keys) + " | S human | S model | Same side |",
        "|---|---|" + "---|" * (len(keys) + 3),
    ]
    same_side = 0
    for c in cases:
        sh, sm = s_of(human[c.id]), s_of(model[c.id])
        side = (sh >= cfg.strategic_cut) == (sm >= cfg.strategic_cut)
        same_side += side
        cells = " | ".join(f"{human[c.id][g]} / {model[c.id][g]}" for g in keys)
        lines.append(
            f"| {c.id} | {c.need.title[:60]} | {cells} | {sh:.2f} | {sm:.2f} | {'yes' if side else 'no'} |"
        )
    quotes = [(r.quote, c) for c in cases for r in rated[f"case:{c.id}"].output.ratings if r.quote.strip()]
    kept = sum(bool(verify_quotes([q], "\n".join(c.requests))[0]) for q, c in quotes)
    all_runs = [run for v in rated.values() for run in v.runs]
    cost = sum(r.cost_usd for r in all_runs)
    lat = [v.latency_ms for v in rated.values()]
    lines += [
        "",
        f"- Strategic side (S ≥ {cfg.strategic_cut}) agrees on {same_side}/{len(cases_all)} needs"
        + (
            f"; {len(lost)} rating(s) failed: "
            + "; ".join(f"{c.id} ({failed[f'case:{c.id}']})" for c in lost)
            if lost
            else ""
        )
        + ".",
        f"- Quotes: {kept}/{len(quotes)} non-empty quotes found verbatim in the requests (the rest are dropped "
        "and flagged in the app).",
        f"- Calls: {len(all_runs)} ({sum(r.outcome != 'ok' for r in all_runs)} not ok) for {len(rated)} ratings "
        f"(seeded needs and cases share calls when the text is identical); ${cost:.4f} in total, "
        f"${cost / max(1, len(rated)):.4f} per rating; latency p50 {percentile(lat, 0.5) / 1000:.1f} s, "
        f"p95 {percentile(lat, 0.95) / 1000:.1f} s (as measured when the calls were made).",
    ]
    return "\n".join(lines) + "\n"


def make_dataset() -> int:
    """Write the template Robert labels: CASE_IDS from the seed, expected left empty. Never overwrites."""
    if DATASET.exists():
        print(f"{DATASET.relative_to(ROOT)} exists; not overwriting labels", file=sys.stderr)
        return 2
    goals = load_priorities(CONFIG / "priorities.yaml").goals
    by_id = {nid: (need, texts) for nid, need, texts in seeded_needs()}
    rows = [
        FitCase(
            id=f"F{i:02d}",
            need=by_id[nid][0],
            requests=by_id[nid][1],
            expected=dict.fromkeys((g.key for g in goals), None),
            author="robert",
            reviewed_by_human=False,
        )
        for i, nid in enumerate(CASE_IDS, 1)
    ]
    DATASET.write_text("".join(r.model_dump_json() + "\n" for r in rows), encoding="utf-8")
    print(
        f"Wrote {len(rows)} cases to {DATASET.relative_to(ROOT)}; rate each goal 0-3 and set reviewed_by_human"
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument(
        "--paid", action="store_true", help="call the API on a cache miss (make eval STEP=fit only)"
    )
    ap.add_argument("--make-dataset", action="store_true", help="write the unlabelled case template")
    args = ap.parse_args(argv)
    if args.make_dataset:
        return make_dataset()
    if args.paid and os.environ.get("EVAL_ALLOW_PAID") != "1":
        print(
            "Refusing: this makes paid model calls. Run it through `make eval STEP=fit`, which asks first.",
            file=sys.stderr,
        )
        return 2
    cfg = load_priorities(CONFIG / "priorities.yaml")
    keys = tuple(g.key for g in cfg.goals)
    try:  # eval-first: no paid call before the human labels exist, so they can't be anchored on the model's
        cases = load_fit_cases(DATASET, keys, require_labels=args.paid)
    except ValueError as exc:
        print(f"Refusing the paid run: {exc}", file=sys.stderr)
        return 2
    needs = seeded_needs()
    items = [(f"seed:{nid}", need, texts) for nid, need, texts in needs]
    items += [(f"case:{c.id}", c.need, c.requests) for c in cases]
    rated, misses, failed = rate_all(items, cfg, paid=args.paid)
    if misses:
        print(f"{len(misses)} call(s) are not in the cache; nothing was written:", file=sys.stderr)
        for m in misses:
            print(f"  {m}", file=sys.stderr)
        return 2
    snapshot = seed_snapshot(needs, rated, failed, cfg)
    SEED_OUT.write_text(json.dumps(snapshot, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"Wrote {SEED_OUT.relative_to(ROOT)}: {len(snapshot['needs'])} needs rated, {len(failed)} failed")
    for key, why in failed.items():
        print(f"  failed {key}: {why}", file=sys.stderr)
    try:
        labelled = load_fit_cases(DATASET, keys)
    except ValueError as exc:
        print(f"No report yet: {exc}", file=sys.stderr)
        return 0
    RESULT_MD.write_text(report(labelled, rated, failed, cfg, FastEmbedder()), encoding="utf-8")
    print(f"Wrote {RESULT_MD.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
