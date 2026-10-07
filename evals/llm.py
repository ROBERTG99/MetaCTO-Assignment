"""LLM strategy eval: `make eval` (paid; settings ask first). Haiku 4.5 extracts once per case; only the
adjudication model varies, so differences are the adjudicator's. Every reply is cached in
evals/results/llm_cache.jsonl: reruns are free and the numbers reproducible.

dev  = the seed replay (as evals/run.py): needs are created from the extraction of their first request,
       the backlog takes the true label after each decision.
test = the frozen 150 cases against the curated backlog (17 needs, their requests, canonical titles).
Routing uses the code in app/ai (policy.decide on routing scores from config/routing.yaml); nothing is tuned.
"""

import argparse
import hashlib
import json
import os
import sys
import threading
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml
from app.ai.gateway import (
    AnthropicClient,
    Gateway,
    LLMClient,
    Reply,
    StepConfig,
    TerminalError,
    TransientError,
    Usage,
)  # fmt: skip
from app.ai.pipeline import _candidate_from, _score
from app.ai.policy import RoutingConfig, decide, load_routing
from app.ai.redact import redact
from app.ai.retrieval import NeedIndex
from app.ai.schemas import Adjudication, Extraction
from app.models import AIRun, Need
from pydantic import BaseModel

from evals.dataset import DATASETS, check_frozen, load_cases
from evals.metrics import Decision

ROOT = Path(__file__).resolve().parents[1]
SEED = ROOT / "backend" / "seed"
CONFIG = ROOT / "config"
RESULTS = ROOT / "evals" / "results"
EXTRACT_MODEL = "claude-haiku-4-5"
STRATEGIES: dict[str, tuple[str, str | None]] = {
    "haiku": ("claude-haiku-4-5", None),
    "sonnet": ("claude-sonnet-5-5", None),  # Sonnet 5.5's default effort (high)
    "sonnet-low": ("claude-sonnet-5-5", "low"),
}


class CachingClient:
    """Wraps a real client: answers from the cache when the exact call was made before. Records the original
    latency per call in a thread-local list, so latency is reported as measured, not as cache hits."""

    def __init__(self, inner: LLMClient, path: Path) -> None:
        self.inner, self.path, self.name = inner, path, f"cached-{inner.name}"
        self._lock = threading.Lock()
        self._local = threading.local()
        self._cache: dict[str, dict[str, Any]] = {}
        if path.exists():
            for line in path.read_text(encoding="utf-8").splitlines():
                entry = json.loads(line)
                self._cache[entry["key"]] = entry

    def latencies(self) -> list[float]:
        if not hasattr(self._local, "lat"):
            self._local.lat = []
        lat: list[float] = self._local.lat
        return lat

    @staticmethod
    def key(step: str, model: str, effort: str | None, system: str, user: str, max_tokens: int) -> str:
        return hashlib.sha256(
            json.dumps([step, model, effort, system, user, max_tokens]).encode()
        ).hexdigest()

    def complete(self, *, step: str, model: str, system: str, user: str, schema: type[BaseModel], max_tokens: int,
                 effort: str | None, inputs: dict[str, Any]) -> Reply:  # fmt: skip
        k = self.key(step, model, effort, system, user, max_tokens)
        hit = self._cache.get(k)
        if hit is None:
            start = time.perf_counter()
            reply = self.inner.complete(step=step, model=model, system=system, user=user, schema=schema,
                                        max_tokens=max_tokens, effort=effort, inputs=inputs)  # fmt: skip
            hit = {"key": k, "step": step, "model": model, "effort": effort, "served_model": reply.model,
                   "output": reply.output.model_dump(), "usage": [reply.usage.input_tokens, reply.usage.output_tokens],
                   "latency_ms": (time.perf_counter() - start) * 1000}  # fmt: skip
            with self._lock:
                self._cache[k] = hit
                with self.path.open("a", encoding="utf-8") as f:
                    f.write(json.dumps(hit, ensure_ascii=False) + "\n")
        self.latencies().append(hit["latency_ms"])
        return Reply(schema.model_validate(hit["output"]), Usage(*hit["usage"]), hit["served_model"])


@dataclass
class Item:
    """One routing decision to evaluate: a request and the backlog it is judged against."""

    ref: str
    split: str
    text: str  # redacted title + description
    role: str
    expected: str | None
    tags: list[str]
    candidates: list[tuple[str, float]] = field(default_factory=list)  # (need key, similarity), best first
    examples: dict[str, list[str]] = field(
        default_factory=dict
    )  # member titles the backlog had at that moment


@dataclass
class Outcome:
    ref: str
    strategy: str
    band: str
    predicted: str | None
    score: float
    top_need: str | None  # best same_need candidate, before the bands (for the threshold sweep)
    top_score: float
    labels: dict[str, str]
    cost: float
    latency_ms: float
    error: str | None = None


def _retrying(fn: Callable[[], Any], attempts: int = 4) -> Any:
    for i in range(attempts):
        try:
            return fn()
        except TransientError:
            if i == attempts - 1:
                raise
            time.sleep(5 * 2**i)
    return None


def _gateway(
    client: LLMClient, model: str, effort: str | None, prices: dict[str, Any], runs: list[AIRun]
) -> Gateway:
    def record(run: AIRun) -> int:
        runs.append(run)
        return len(runs)

    steps = {"extract": StepConfig(EXTRACT_MODEL, 2000), "adjudicate": StepConfig(model, 4000, effort)}
    return Gateway(client=client, steps=steps, prices=prices, record=record)


def needs_from_truth() -> dict[str, Need]:
    truth = json.loads((SEED / "ground_truth.json").read_text(encoding="utf-8"))
    return {k: Need(id=i + 1, title=v["title"], problem=v["title"], persona=v["persona"], product_area=v["product_area"])
            for i, (k, v) in enumerate(truth["needs"].items())}  # fmt: skip


def dev_items(
    index_factory: Callable[[], NeedIndex], extractions: dict[str, Extraction]
) -> tuple[list[Item], dict[str, Need], dict[str, list[str]]]:
    """Replay in arrival order. A need is born from the extraction of its first request that has one. Each item
    sees the backlog as it was when it arrived: its candidates and example titles never include itself or later ones.
    """
    truth = json.loads((SEED / "ground_truth.json").read_text(encoding="utf-8"))
    reqs = {r["ref"]: r for r in json.loads((SEED / "requests.json").read_text(encoding="utf-8"))}
    index = index_factory()
    needs: dict[str, Need] = {}
    examples: dict[str, list[str]] = {}
    items: list[Item] = []
    for n, ref in enumerate(truth["arrival_order"]):
        r = reqs[ref]
        text = redact(f"{r['title']}\n{r['description']}")
        gold = truth["requests"][ref]["need"]
        key = gold or f"new:{ref}"
        hits = [(h.need_id, h.score) for h in index.search(text, k=5)]
        snapshot = {k: v[:2] for k, v in examples.items()}
        items.append(Item(ref, "dev", text, "", gold if key in needs else None,
                          ["repeat" if key in needs else "first_appearance"], hits, snapshot))  # fmt: skip
        ex = extractions.get(ref)
        if key not in needs and ex is not None:
            needs[key] = Need(id=n + 1, title=ex.need_statement, problem=ex.problem, persona=ex.persona,
                              product_area=ex.product_area)  # fmt: skip
            index.add_canonical(key, ex.need_statement)
        index.add_request(ref, key, text)
        examples.setdefault(key, []).append(r["title"])
    return items, needs, examples


def test_items(index: NeedIndex, examples: dict[str, list[str]]) -> list[Item]:
    snapshot = {k: v[:2] for k, v in examples.items()}  # the test backlog is complete before any case arrives
    items = []
    for c in load_cases(DATASETS / "test.jsonl"):
        text = redact(c.request.text)
        hits = [(h.need_id, h.score) for h in index.search(text, k=5)]
        tags = [c.slice, "handwritten" if c.reviewed_by_human else "generated"]
        items.append(
            Item(c.id, "test", text, c.request.requester_role, c.expected.need, tags, hits, snapshot)
        )
    return items


def route_one(
    item: Item, ex: Extraction, adj: Adjudication, needs: dict[str, Need], cfg: RoutingConfig
) -> tuple[str, str | None, float, str | None, float, dict[str, str]]:
    """Route with the app's code. Returns band, predicted need key, score, best same_need key and its score
    (before the bands, for the threshold sweep), and the label per candidate key."""
    keys = [k for k, _ in item.candidates if k in needs]
    id_of = {k: needs[k].id for k in keys}
    key_of = {i: k for k, i in id_of.items() if i is not None}
    by_id = {i: needs[k] for i, k in key_of.items()}
    sims = {id_of[k]: s for k, s in item.candidates if k in needs and id_of[k] is not None}
    scored = _score(adj, by_id, {i: s for i, s in sims.items() if i is not None}, ex, cfg)
    route = decide(scored, cfg)
    best = max((x for x in scored if x.label == "same_need"), key=lambda x: x.score, default=None)
    labels = {key_of[x.need_id]: x.label for x in scored}
    predicted = key_of[route.need_id] if route.need_id is not None else None
    return (
        route.band,
        predicted,
        route.score,
        key_of[best.need_id] if best else None,
        best.score if best else 0.0,
        labels,
    )


def run(strategies: list[str], splits: list[str], workers: int = 8) -> dict[str, Any]:
    from app.ai.embeddings import FastEmbedder
    from app.config import get_settings

    frozen = check_frozen()
    cfg = load_routing(CONFIG / "routing.yaml")
    prices = yaml.safe_load((CONFIG / "prices.yaml").read_text(encoding="utf-8"))
    settings = get_settings()
    key = settings.anthropic_api_key.get_secret_value() if settings.anthropic_api_key else None
    client = CachingClient(AnthropicClient(60.0, 2, api_key=key), RESULTS / "llm_cache.jsonl")
    embedder = FastEmbedder(cache_dir=ROOT / "backend" / ".cache" / "fastembed")
    seed_reqs = json.loads((SEED / "requests.json").read_text(encoding="utf-8"))
    people = {p["ref"]: p["role"] for p in json.loads((SEED / "requesters.json").read_text(encoding="utf-8"))}

    # phase 1: one Haiku extraction per request or case, shared by every strategy
    to_extract: list[tuple[str, str, str]] = []
    if "dev" in splits:
        to_extract += [
            (r["ref"], redact(f"{r['title']}\n{r['description']}"), people[r["requester"]]) for r in seed_reqs
        ]
    test_cases = load_cases(DATASETS / "test.jsonl") if "test" in splits else []
    to_extract += [(c.id, redact(c.request.text), c.request.requester_role) for c in test_cases]

    def extract(job: tuple[str, str, str]) -> tuple[str, Extraction | None, float, float, str | None]:
        ref, text, role = job
        runs: list[AIRun] = []
        client.latencies().clear()
        gw = _gateway(client, EXTRACT_MODEL, None, prices, runs)
        try:
            ex, _ = _retrying(lambda: gw.extract(text=text, why=None, role=role))
            err = None
        except (TerminalError, TransientError) as exc:
            ex, err = None, str(exc)
        return ref, ex, sum(r.cost_usd for r in runs), sum(client.latencies()), err

    with ThreadPoolExecutor(workers) as pool:
        ext = {ref: (ex, cost, lat, err) for ref, ex, cost, lat, err in pool.map(extract, to_extract)}
    extractions = {ref: v[0] for ref, v in ext.items() if v[0] is not None}

    # phase 2: the backlog each decision sees, then one adjudication per (strategy, item)
    work: list[tuple[str, Item, dict[str, Need], dict[str, list[str]]]] = []
    if "dev" in splits:
        items, needs, examples = dev_items(lambda: NeedIndex(embedder), extractions)
        roles = {r["ref"]: people[r["requester"]] for r in seed_reqs}
        for it in items:
            it.role = roles[it.ref]
        work += [(s, it, needs, examples) for s in strategies for it in items]
    if "test" in splits:
        needs_t = needs_from_truth()
        index = NeedIndex(embedder)
        truth = json.loads((SEED / "ground_truth.json").read_text(encoding="utf-8"))
        ex_t: dict[str, list[str]] = {}
        for r in seed_reqs:
            g = truth["requests"][r["ref"]]["need"]
            if g:
                index.add_request(r["ref"], g, redact(f"{r['title']}\n{r['description']}"))
                ex_t.setdefault(g, []).append(r["title"])
        for k, n in needs_t.items():
            index.add_canonical(k, n.title)
        work += [(s, it, needs_t, ex_t) for s in strategies for it in test_items(index, ex_t)]

    def adjudicate(job: tuple[str, Item, dict[str, Need], dict[str, list[str]]]) -> Outcome:
        strategy, it, needs, _examples = job
        ex_cost, ex_lat = ext[it.ref][1], ext[it.ref][2]
        ex = extractions.get(it.ref)
        if ex is None:
            return Outcome(
                it.ref, strategy, "failed", None, 0.0, None, 0.0, {}, ex_cost, ex_lat, ext[it.ref][3]
            )
        if not it.candidates:
            return Outcome(it.ref, strategy, "new", None, 0.0, None, 0.0, {}, ex_cost, ex_lat)
        model, effort = STRATEGIES[strategy]
        runs: list[AIRun] = []
        client.latencies().clear()
        gw = _gateway(client, model, effort, prices, runs)
        cands = [_candidate_from(needs[k], it.examples.get(k, [])) for k, _ in it.candidates if k in needs]
        try:
            adj, _ = _retrying(lambda: gw.adjudicate(text=it.text, why=None, candidates=cands, role=it.role,
                                                     extracted=f"{ex.need_statement} (persona: {ex.persona}; area: {ex.product_area})"))  # fmt: skip
        except (TerminalError, TransientError) as exc:
            cost = ex_cost + sum(r.cost_usd for r in runs)
            return Outcome(
                it.ref,
                strategy,
                "failed",
                None,
                0.0,
                None,
                0.0,
                {},
                cost,
                ex_lat + sum(client.latencies()),
                str(exc),
            )
        band, predicted, score, top_need, top_score, labels = route_one(it, ex, adj, needs, cfg)
        cost = ex_cost + sum(r.cost_usd for r in runs)
        return Outcome(it.ref, strategy, band, predicted, score, top_need, top_score, labels, cost,
                       ex_lat + sum(client.latencies()))  # fmt: skip

    with ThreadPoolExecutor(workers) as pool:
        outcomes = list(pool.map(adjudicate, work))

    by_split: dict[str, list[tuple[Item, Outcome]]] = {}
    for (_s, it, _, _), o in zip(work, outcomes, strict=True):
        by_split.setdefault(it.split, []).append((it, o))
    RESULTS.mkdir(exist_ok=True)
    for split, rows in by_split.items():
        path = RESULTS / f"llm_cases_{split}.jsonl"
        fresh = {(o.strategy, it.ref): {
            "split": split, "ref": it.ref, "tags": it.tags, "expected": it.expected,
            "extract_cost": ext[it.ref][1], "extract_latency_ms": ext[it.ref][2], "candidates": it.candidates,
            "examples": it.examples,
            "extraction": extractions[it.ref].model_dump() if it.ref in extractions else None, **o.__dict__,
        } for it, o in rows}  # fmt: skip
        kept = []
        if path.exists():  # merge: a run of some strategies keeps the others' rows
            for line in path.read_text(encoding="utf-8").splitlines():
                old = json.loads(line)
                if (old["strategy"], old["ref"]) not in fresh:
                    kept.append(old)
        with path.open("w", encoding="utf-8") as f:
            for row in [*kept, *fresh.values()]:
                f.write(json.dumps(row, ensure_ascii=False) + "\n")
    served = sorted({e["served_model"] for e in client._cache.values()})
    meta = {
        "run_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "git": _git_sha(), "frozen_sha256": frozen, "strategies": strategies, "splits": list(by_split),
        "extract_model": EXTRACT_MODEL, "adjudicators": {k: STRATEGIES[k] for k in strategies},
        "prompts": ["extract_need_v1", "adjudicate_v1"], "served_models": served,
        "routing": {"auto": cfg.auto, "suggest": cfg.suggest, "s_min": cfg.s_min, "s_max": cfg.s_max},
        "outcomes": len(outcomes), "failed": sum(o.band == "failed" for o in outcomes),
    }  # fmt: skip
    (RESULTS / "llm_run.json").write_text(json.dumps(meta, indent=2) + "\n")
    return meta


def _git_sha() -> str:
    import subprocess

    sha = subprocess.run(
        ["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, capture_output=True, text=True
    ).stdout.strip()
    dirty = subprocess.run(
        ["git", "status", "--porcelain"], cwd=ROOT, capture_output=True, text=True
    ).stdout.strip()
    return sha + ("-dirty" if dirty else "")


def decisions(rows: list[dict[str, Any]]) -> list[Decision]:
    return [Decision(r["expected"], r["predicted"], r["score"], r["band"], tuple(c for c, _ in r["candidates"]), r["latency_ms"])
            for r in rows]  # fmt: skip


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--strategies", default="haiku,sonnet,sonnet-low")
    ap.add_argument("--splits", default="dev,test")
    ap.add_argument("--workers", type=int, default=8)
    args = ap.parse_args(argv)
    if os.environ.get("EVAL_ALLOW_PAID") != "1":
        print(
            "Refusing: this makes paid model calls. Run it through `make eval`, which asks first.",
            file=sys.stderr,
        )
        return 2
    strategies = [s for s in args.strategies.split(",") if s]
    unknown = set(strategies) - set(STRATEGIES)
    if unknown:
        print(f"unknown strategies: {sorted(unknown)}", file=sys.stderr)
        return 2
    summary = run(strategies, [s for s in args.splits.split(",") if s], args.workers)
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
