"""Build backend/seed/snapshot.json from the cached Haiku dev replay: `make snapshot`. No API calls.

The replay is the one in evals/llm.py (Haiku 4.5 extraction and adjudication, prompts v1). Its client
raises on a cache miss instead of calling the API, and every miss is reported. Decisions are re-routed
with the locked config/routing.yaml, so the snapshot matches what the app would decide today.

Caveat: the replay is teacher-forced (each decision saw the backlog with the true labels so far). Applied in
arrival order, a few later decisions were made against a backlog that differs from the one the snapshot
builds. The snapshot is a demo of real model output, not a simulation of the app's history.
"""

import hashlib
import json
import sys
from typing import Any

from app.ai.embeddings import FastEmbedder
from app.ai.gateway import Reply
from app.ai.pipeline import _candidate_from, _judgment, _score
from app.ai.policy import load_routing
from app.ai.redact import redact
from app.ai.retrieval import NeedIndex
from app.ai.schemas import Extraction
from app.models import AIRun

from evals.llm import (
    CONFIG,
    EXTRACT_MODEL,
    RESULTS,
    ROOT,
    SEED,
    STRATEGIES,
    CachingClient,
    _gateway,
    dev_items,
    route_one,
)

OUT = ROOT / "backend" / "seed" / "snapshot.json"
CACHE_FILE = RESULTS / "llm_cache.jsonl"


class MissingFromCache(Exception):
    pass


class NoNetwork:
    """Answers nothing: a call that isn't in the cache is a miss, never a paid request."""

    name = "no-network"

    def complete(self, *, step: str, model: str, **_: Any) -> Reply:
        raise MissingFromCache(f"{step} with {model}")


def _runs(runs: list[AIRun], latencies: list[float]) -> list[dict[str, Any]]:
    return [{"step": r.step, "model": r.model, "prompt_version": r.prompt_version, "input_tokens": r.input_tokens,
             "output_tokens": r.output_tokens, "cost_usd": r.cost_usd, "latency_ms": int(lat), "outcome": r.outcome}
            for r, lat in zip(runs, latencies, strict=True)]  # fmt: skip


def build() -> dict[str, Any]:
    import yaml

    prices = yaml.safe_load((CONFIG / "prices.yaml").read_text(encoding="utf-8"))
    cfg = load_routing(CONFIG / "routing.yaml")
    client = CachingClient(NoNetwork(), CACHE_FILE)
    seed_reqs = json.loads((SEED / "requests.json").read_text(encoding="utf-8"))
    people = {p["ref"]: p["role"] for p in json.loads((SEED / "requesters.json").read_text(encoding="utf-8"))}
    misses: list[str] = []
    extractions: dict[str, Extraction] = {}
    runs_by_ref: dict[str, list[dict[str, Any]]] = {}
    for r in seed_reqs:
        runs: list[AIRun] = []
        client.latencies().clear()
        gw = _gateway(client, EXTRACT_MODEL, None, prices, runs)
        try:
            ex, _ = gw.extract(
                text=redact(f"{r['title']}\n{r['description']}"), why=None, role=people[r["requester"]]
            )
            extractions[r["ref"]] = ex
            runs_by_ref[r["ref"]] = _runs(runs, client.latencies())
        except MissingFromCache as exc:
            misses.append(f"{r['ref']}: {exc}")
    items, needs, _ = dev_items(
        lambda: NeedIndex(FastEmbedder(cache_dir=ROOT / "backend" / ".cache" / "fastembed")), extractions
    )
    model, effort = STRATEGIES["haiku"]
    requests: dict[str, Any] = {}
    for it in items:
        it.role = people[next(r["requester"] for r in seed_reqs if r["ref"] == it.ref)]
        found = extractions.get(it.ref)
        if found is None:
            continue
        ex = found
        decision: dict[str, Any] = {"band": "new", "need_key": None, "score": 0.0, "label": None, "model_confidence": None,
                                    "rationale": "No existing need matched; created a new one.", "quotes": [], "related": []}  # fmt: skip
        if it.candidates:
            runs = []
            client.latencies().clear()
            gw = _gateway(client, model, effort, prices, runs)
            cands = [
                _candidate_from(needs[k], it.examples.get(k, [])) for k, _ in it.candidates if k in needs
            ]
            try:
                adj, _ = gw.adjudicate(text=it.text, why=None, candidates=cands, role=it.role,
                                       extracted=f"{ex.need_statement} (persona: {ex.persona}; area: {ex.product_area})")  # fmt: skip
            except MissingFromCache as exc:
                misses.append(f"{it.ref}: {exc}")
                continue
            runs_by_ref[it.ref] += _runs(runs, client.latencies())
            band, predicted, score, _top, _ts, labels = route_one(it, ex, adj, needs, cfg)
            scores = _scores(it, ex, adj, needs, cfg)
            if band != "new":
                conf, why, quotes = _judgment(adj, needs[predicted].id, it.text)  # type: ignore[index]
                decision = {"band": band, "need_key": predicted, "score": score, "label": "same_need",
                            "model_confidence": conf, "rationale": why, "quotes": quotes, "related": []}  # fmt: skip
            for key, label in labels.items():
                if label in ("related", "same_need") and key != predicted:
                    conf, why, quotes = _judgment(adj, needs[key].id, it.text)
                    decision["related"].append({"need_key": key, "label": label, "model_confidence": conf,
                                                "rationale": why, "quotes": quotes, "score": scores[key]})  # fmt: skip
        requests[it.ref] = {"extraction": ex.model_dump(), "decision": decision, "runs": runs_by_ref.get(it.ref, []),
                            "first_appearance": "first_appearance" in it.tags, "replay_need_key": _key(it)}  # fmt: skip
    if misses:
        return {"misses": misses}
    used = {d["decision"]["need_key"] for d in requests.values() if d["decision"]["need_key"]}
    used |= {
        d["replay_need_key"]
        for d in requests.values()
        if d["decision"]["band"] == "new" and d["first_appearance"]
    }
    used |= {x["need_key"] for d in requests.values() for x in d["decision"]["related"]}
    snapshot = {
        "about": "Recorded Haiku 4.5 output from the cached dev replay (evals/results/llm_cache.jsonl), re-routed with "
        "the locked config/routing.yaml. Loaded by `make seed`. See evals/snapshot.py for the teacher-forcing caveat.",
        "cache_sha256": hashlib.sha256(CACHE_FILE.read_bytes()).hexdigest(),
        "prompts": ["extract_need_v1", "adjudicate_v1"],
        "routing": {
            "auto": cfg.auto,
            "suggest": cfg.suggest,
            "s_min": cfg.s_min,
            "s_max": cfg.s_max,
            "weights": [cfg.w_label, cfg.w_sim, cfg.w_fields],
        },
        "arrival_order": [it.ref for it in items],
        "needs": {
            k: {"title": n.title, "problem": n.problem, "persona": n.persona, "product_area": n.product_area}
            for k, n in needs.items()
            if k in used
        },
        "requests": requests,
    }
    return snapshot


def _scores(it: Any, ex: Extraction, adj: Any, needs: dict[str, Any], cfg: Any) -> dict[str, float]:
    """The routing score of every candidate, as the app computes it (for related suggestions)."""
    key_of = {needs[k].id: k for k, _ in it.candidates if k in needs}
    sims = {needs[k].id: sim for k, sim in it.candidates if k in needs}
    return {
        key_of[x.need_id]: x.score
        for x in _score(adj, {i: needs[k] for i, k in key_of.items()}, sims, ex, cfg)
    }


def _key(it: Any) -> str:
    truth = json.loads((SEED / "ground_truth.json").read_text(encoding="utf-8"))
    return str(truth["requests"][it.ref]["need"] or f"new:{it.ref}")


def main() -> int:
    out = build()
    if "misses" in out:
        print(f"{len(out['misses'])} call(s) are not in the cache; nothing was written:", file=sys.stderr)
        for m in out["misses"]:
            print(f"  {m}", file=sys.stderr)
        return 2
    OUT.write_text(json.dumps(out, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    bands: dict[str, int] = {}
    for d in out["requests"].values():
        bands[d["decision"]["band"]] = bands.get(d["decision"]["band"], 0) + 1
    print(
        f"Wrote {OUT.relative_to(ROOT)}: {len(out['requests'])} requests, {len(out['needs'])} needs, bands {bands}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
