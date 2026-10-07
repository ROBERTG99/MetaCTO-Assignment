"""Eval runner. `make eval-offline SPLIT=dev|test STRATEGY=baseline` (free), `make eval-tune` (dev only).

dev  = the seed stream replayed in arrival order. Each request is routed against the backlog built so far.
       The decision is right if it links to the right existing need, or creates a new one when its cluster
       first appears. After each decision the backlog takes the true label (as if a PM had corrected it),
       so every decision is judged on a correct backlog and errors don't compound.
test = the frozen 150 cases, each routed against the full seeded backlog (17 needs, their requests, and one
       canonical problem-plus-persona text per need). The runner refuses to run if the set isn't frozen.
"""

import argparse
import json
import re
import subprocess
import sys
import time
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml
from app.ai.baseline import Routed, Thresholds, load_thresholds, route
from app.ai.embeddings import Embedder, FastEmbedder
from app.ai.retrieval import Hit, NeedIndex

from evals.dataset import DATASETS, Case, FrozenError, check_frozen, load_cases
from evals.metrics import (
    Decision,
    Rate,
    accuracy_by_bucket,
    decision_accuracy,
    duplicate_prf,
    false_merge_rate,
    percentile,
    recall_at_k,
)
from evals.tune import NEVER, choose_thresholds

ROOT = Path(__file__).resolve().parents[1]
SEED = ROOT / "backend" / "seed"
ROUTING = ROOT / "config" / "routing.yaml"
RESULTS = ROOT / "evals" / "results"
CACHE = ROOT / "backend" / ".cache" / "fastembed"
BUCKETS = [0.0, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0]
TOP_KEY = re.compile(r"^[A-Za-z_][\w-]*:")
K = 5
Tagged = list[tuple[str, Decision]]


def _json(name: str, seed: Path) -> Any:
    return json.loads((seed / name).read_text(encoding="utf-8"))


def _decide(index: NeedIndex, text: str, th: Thresholds | None) -> tuple[list[Hit], float, Routed | None]:
    start = time.perf_counter()
    hits = index.search(text, k=K)
    routed = route(hits, th) if th else None
    return hits, (time.perf_counter() - start) * 1000, routed


def _decision(expected: str | None, hits: list[Hit], ms: float, routed: Routed | None) -> Decision:
    candidates = tuple(h.need_id for h in hits)
    if routed is None:  # raw, for tuning: the top candidate and its score, before any threshold
        top = hits[0] if hits else None
        return Decision(
            expected, top.need_id if top else None, top.score if top else 0.0, "raw", candidates, ms
        )
    return Decision(expected, routed.need_id, routed.score, routed.band, candidates, ms)


def replay_dev(embedder: Embedder, th: Thresholds | None, seed: Path = SEED) -> Tagged:
    """Tags each decision "first_appearance" (expected new) or "repeat". Noise is always expected new; the
    backlog then gets a need for it, as a PM would create one."""
    truth = _json("ground_truth.json", seed)
    requests = {r["ref"]: r for r in _json("requests.json", seed)}
    index, seen = NeedIndex(embedder), set()
    out: Tagged = []
    for ref in truth["arrival_order"]:
        r = requests[ref]
        text = f"{r['title']}\n{r['description']}"
        gold = truth["requests"][ref]["need"]
        expected = gold if gold in seen else None
        hits, ms, routed = _decide(index, text, th)
        out.append(("repeat" if expected else "first_appearance", _decision(expected, hits, ms, routed)))
        need_key = gold or f"new:{ref}"
        index.add_request(ref, need_key, text)
        seen.add(need_key)
    return out


def seeded_backlog(embedder: Embedder, seed: Path = SEED) -> NeedIndex:
    """The labelled needs, their requests and their canonical titles. Unlike the dev replay, the unlabelled
    noise request is not a need here: the test backlog is the curated one."""
    truth = _json("ground_truth.json", seed)
    index = NeedIndex(embedder)
    for r in _json("requests.json", seed):
        need = truth["requests"][r["ref"]]["need"]
        if need is not None:
            index.add_request(r["ref"], need, f"{r['title']}\n{r['description']}")
    for need, info in truth["needs"].items():
        index.add_canonical(need, info["title"])
    return index


def run_test(
    embedder: Embedder, th: Thresholds, cases: list[Case] | None = None, seed: Path = SEED
) -> Tagged:
    """Each case is tagged twice: its slice, and handwritten or generated (which together make "all")."""
    index = seeded_backlog(embedder, seed)
    out: Tagged = []
    for case in cases if cases is not None else load_cases(DATASETS / "test.jsonl"):
        hits, ms, routed = _decide(index, case.request.text, th)
        decision = _decision(case.expected.need, hits, ms, routed)
        out += [(case.slice, decision), ("handwritten" if case.reviewed_by_human else "generated", decision)]
    return out


def overall(tagged: Tagged, split: str) -> list[Decision]:
    """Every decision exactly once."""
    return [d for t, d in tagged if split == "dev" or t in ("handwritten", "generated")]


def _rate(r: Rate) -> dict[str, Any]:
    lo, hi = r.interval
    return {"k": r.k, "n": r.n, "value": r.value, "lo": lo, "hi": hi}


def _latency(ds: list[Decision]) -> dict[str, float] | None:
    if not ds:
        return None
    ms = [d.latency_ms for d in ds]
    return {"p50": percentile(ms, 0.5), "p95": percentile(ms, 0.95)}


def summarize(ds: list[Decision]) -> dict[str, Any]:
    prf = duplicate_prf(ds)
    auto = [d for d in ds if d.band == "auto"]
    return {
        "n": len(ds),
        "bands": dict(Counter(d.band for d in ds)),
        "accuracy": _rate(decision_accuracy(ds)),
        "dup_precision": _rate(prf.precision),
        "dup_recall": _rate(prf.recall),
        "dup_f1": prf.f1,
        "false_merge_all_links": _rate(false_merge_rate(ds)),
        "false_merge_auto": _rate(false_merge_rate(auto)),
        "recall_at": {k: _rate(recall_at_k(ds, k)) for k in (1, 3, 5)},
        "by_bucket": [[lo, hi, _rate(r)] for lo, hi, r in accuracy_by_bucket(ds, BUCKETS)],
        "latency_ms": _latency(ds),
    }


def _pct(r: dict[str, Any]) -> str:
    if r["value"] is None:
        return "n/a (n=0)"
    return f"{100 * r['value']:.1f}% ({r['k']}/{r['n']}, CI {100 * r['lo']:.0f}-{100 * r['hi']:.0f}%)"


def markdown(split: str, total: dict[str, Any], slices: dict[str, dict[str, Any]], th: Thresholds) -> str:
    lines = [
        f"#### {split}: baseline (auto ≥ {th.auto:.4f}, suggest ≥ {th.suggest:.4f})",
        "",
        "| Slice | n | Accuracy | False merges (all links) | False merges (auto) | Recall@1 | Recall@3 | Recall@5 "
        "| Bands auto/suggest/new |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for name, m in [("all", total), *sorted(slices.items())]:
        b = m["bands"]
        lines.append(
            f"| {name} | {m['n']} | {_pct(m['accuracy'])} | {_pct(m['false_merge_all_links'])} | "
            f"{_pct(m['false_merge_auto'])} | {_pct(m['recall_at'][1])} | {_pct(m['recall_at'][3])} | "
            f"{_pct(m['recall_at'][5])} | {b.get('auto', 0)}/{b.get('suggest', 0)}/{b.get('new', 0)} |"
        )
    buckets = ", ".join(
        f"[{lo:.1f}, {hi:.1f}{']' if hi == BUCKETS[-1] else ')'} {_pct(r)}"
        for lo, hi, r in total["by_bucket"]
        if r["n"]
    )
    lines += [
        "",
        f"Duplicates: precision {_pct(total['dup_precision'])}, recall {_pct(total['dup_recall'])}, "
        f"F1 {total['dup_f1']:.3f}. Latency per decision (embed + search): "
        f"p50 {total['latency_ms']['p50']:.1f} ms, p95 {total['latency_ms']['p95']:.1f} ms.",
        "",
        f"Accuracy by similarity bucket: {buckets}",
    ]
    return "\n".join(lines)


def git_sha() -> str:
    sha = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, capture_output=True, text=True)
    dirty = subprocess.run(["git", "status", "--porcelain"], cwd=ROOT, capture_output=True, text=True)
    return sha.stdout.strip() + ("-dirty" if dirty.stdout.strip() else "")


def replace_block(text: str, key: str, values: dict[str, Any]) -> str:
    """Replace one top-level YAML block, keeping every other line (and its comments) as written.

    The block ends at the next top-level key, so a comment inside it doesn't end it early. The result is
    re-parsed and checked: the block holds exactly `values` and every other key is unchanged.
    """
    block = yaml.safe_dump({key: values}, sort_keys=False, allow_unicode=True)
    lines = text.splitlines(keepends=True)
    start = next((i for i, line in enumerate(lines) if line.startswith(f"{key}:")), None)
    if start is None:
        out = (text.rstrip("\n") + "\n\n" if text.strip() else "") + block
    else:
        end = next((i for i in range(start + 1, len(lines)) if TOP_KEY.match(lines[i])), len(lines))
        while end > start + 1 and (lines[end - 1].strip() == "" or lines[end - 1].startswith("#")):
            end -= 1  # blank lines and comments just above the next block belong to it
        out = "".join(lines[:start]) + block + "".join(lines[end:])
    before, after = yaml.safe_load(text) or {}, yaml.safe_load(out) or {}
    if after.get(key) != values or {k: v for k, v in after.items() if k != key} != {
        k: v for k, v in before.items() if k != key
    }:
        raise ValueError(f"replacing {key} in the YAML would change other content; edit it by hand")
    return out


def tune(embedder: Embedder) -> Thresholds:
    raw = [d for _, d in replay_dev(embedder, th=None)]
    th = choose_thresholds(raw)
    rule = (
        f"auto: lowest similarity with >=97% precision on >=10 links ({NEVER} = never); "
        "suggest: highest that keeps 95% of the remaining true duplicates. Stored unrounded."
    )
    meta = {
        "auto": th.auto,
        "suggest": th.suggest,
        "tuned_on": "dev (seed replay)",
        "n": len(raw),
        "embedding_model": embedder.model_name,
        "rule": rule,
        "tuned_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "git": git_sha(),
    }
    ROUTING.parent.mkdir(exist_ok=True)
    text = ROUTING.read_text(encoding="utf-8") if ROUTING.exists() else ""
    ROUTING.write_text(replace_block(text, "baseline", meta), encoding="utf-8")
    return th


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--split", choices=["dev", "test"], default="dev")
    ap.add_argument("--strategy", choices=["baseline"], default="baseline")
    ap.add_argument(
        "--tune", action="store_true", help="choose thresholds on dev and write config/routing.yaml"
    )
    args = ap.parse_args(argv)
    try:
        frozen = check_frozen()
    except FrozenError as exc:
        print(f"Refusing to run: {exc}", file=sys.stderr)
        return 2
    embedder = FastEmbedder(cache_dir=CACHE)
    if args.tune:
        if args.split != "dev":
            print("Refusing to tune on the test split.", file=sys.stderr)
            return 2
        th = tune(embedder)
        print(f"Wrote {ROUTING.relative_to(ROOT)}: auto {th.auto}, suggest {th.suggest}")
        return 0
    if not ROUTING.exists():
        print("No thresholds yet: run `make eval-tune` first.", file=sys.stderr)
        return 2
    th = load_thresholds(ROUTING)
    tagged = replay_dev(embedder, th) if args.split == "dev" else run_test(embedder, th)
    slices = {tag: summarize([d for t, d in tagged if t == tag]) for tag in sorted({t for t, _ in tagged})}
    total = summarize(overall(tagged, args.split))
    payload = {
        "split": args.split,
        "strategy": args.strategy,
        "thresholds": th.__dict__,
        "git": git_sha(),
        "frozen_sha256": frozen,
        "embedding_model": embedder.model_name,
        "run_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "overall": total,
        "slices": slices,
    }
    RESULTS.mkdir(exist_ok=True)
    (RESULTS / f"{args.split}_{args.strategy}.json").write_text(json.dumps(payload, indent=2) + "\n")
    md = markdown(args.split, total, slices, th)
    (RESULTS / f"{args.split}_{args.strategy}.md").write_text(md + "\n")
    print(md)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
