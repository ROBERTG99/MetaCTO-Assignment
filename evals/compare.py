"""Compare strategies from saved per-case results (free; no model calls). `make eval-compare`.

Reads evals/results/llm_cases_{dev,test}.jsonl (from `make eval`) and recomputes the baseline per case
(evals.run, offline; its sub-10 ms latency is re-measured on every run, so only those cells drift).
Writes evals/results/comparison.json and comparison.md. Decisions follow the rule in llm-code.md: choose
on dev, confirm on test.
"""

import json
from collections import defaultdict
from itertools import pairwise
from pathlib import Path
from typing import Any

from app.ai.baseline import load_thresholds
from app.ai.embeddings import FastEmbedder

from evals.metrics import (
    Decision,
    Rate,
    accuracy_by_bucket,
    decision_accuracy,
    duplicate_prf,
    false_merge_rate,
    percentile,
    recall_at_k,
)  # fmt: skip
from evals.run import CACHE, ROUTING, overall, replay_dev, run_test
from evals.tune import choose_auto

ROOT = Path(__file__).resolve().parents[1]
RESULTS = ROOT / "evals" / "results"
BUCKETS = [0.0, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0]
ORDER = ["baseline", "haiku", "sonnet", "sonnet-low"]
Row = dict[str, Any]


def pct(r: Rate) -> str:
    if r.value is None:
        return "n/a"
    lo, hi = r.interval
    return f"{100 * r.value:.1f}% ({r.k}/{r.n}; {100 * lo:.0f}-{100 * hi:.0f})"


def load(split: str) -> dict[str, list[Row]]:
    rows: dict[str, list[Row]] = defaultdict(list)
    path = RESULTS / f"llm_cases_{split}.jsonl"
    for line in path.read_text(encoding="utf-8").splitlines() if path.exists() else []:
        r = json.loads(line)
        rows[r["strategy"]].append(r)
    return rows


def _decisions(rows: list[Row], for_accuracy: bool) -> list[Decision]:
    """A failure is a wrong decision (for accuracy) but never a link (for precision and false merges)."""
    out = []
    for r in rows:
        predicted = "__failed__" if for_accuracy and r["band"] == "failed" else r["predicted"]
        out.append(Decision(r["expected"], predicted, r["score"], r["band"], tuple(c for c, _ in r["candidates"]),
                            r["latency_ms"]))  # fmt: skip
    return out


def summarize(rows: list[Row]) -> dict[str, Any]:
    acc_ds, link_ds = _decisions(rows, True), _decisions(rows, False)
    prf = duplicate_prf(link_ds)
    lat = [r["latency_ms"] for r in rows]
    return {
        "n": len(rows),
        "accuracy": decision_accuracy(acc_ds),
        "precision": prf.precision,
        "recall": prf.recall,
        "f1": prf.f1,
        "fm_links": false_merge_rate(link_ds),
        "fm_auto": false_merge_rate([d for d in link_ds if d.band == "auto"]),
        "bands": {b: sum(r["band"] == b for r in rows) for b in ("auto", "suggest", "new", "failed")},
        "recall5": recall_at_k(link_ds, 5),
        "p50": percentile(lat, 0.5) if lat else 0.0,
        "p95": percentile(lat, 0.95) if lat else 0.0,
        "cost": sum(r["cost"] for r in rows) / len(rows) if rows else 0.0,
        "buckets": accuracy_by_bucket(acc_ds, BUCKETS),
    }


def cascade_rows(haiku: dict[str, Row], sonnet: dict[str, Row]) -> list[Row]:
    """Haiku first; its gray zone (suggest) escalates to Sonnet. Cost and latency: all of Haiku, plus Sonnet's
    adjudication only (the extraction is shared)."""
    out = []
    for ref, h in haiku.items():
        if h["band"] == "suggest" and ref in sonnet:
            s = sonnet[ref]
            out.append({**s, "cost": h["cost"] + s["cost"] - s["extract_cost"],
                        "latency_ms": h["latency_ms"] + s["latency_ms"] - s["extract_latency_ms"]})  # fmt: skip
        else:
            out.append(h)
    return out


def baseline_rows(split: str) -> list[Row]:
    th = load_thresholds(ROUTING)
    emb = FastEmbedder(cache_dir=CACHE)
    tagged = replay_dev(emb, th) if split == "dev" else run_test(emb, th)
    ds = overall(tagged, split)
    if split == "dev":
        truth = json.loads((ROOT / "backend" / "seed" / "ground_truth.json").read_text())
        refs, tags = truth["arrival_order"], [[t] for t, _ in tagged]
    else:
        from evals.dataset import DATASETS, load_cases

        cases = load_cases(DATASETS / "test.jsonl")
        refs = [c.id for c in cases]
        tags = [[c.slice, "handwritten" if c.reviewed_by_human else "generated"] for c in cases]
    return [{"ref": ref, "tags": t, "expected": d.expected, "predicted": d.predicted, "score": d.score, "band": d.band,
             "candidates": [[c, 0.0] for c in d.candidates], "latency_ms": d.latency_ms, "cost": 0.0,
             "top_need": d.predicted, "top_score": d.score} for ref, t, d in zip(refs, tags, ds, strict=True)]  # fmt: skip


def table(results: dict[str, dict[str, Any]], title: str) -> list[str]:
    out = [f"**{title}**", "",
           "| Strategy | n | Accuracy | Dup precision | Dup recall | F1 | False merges (links) | False merges (auto) | auto/suggest/new/failed | p50 / p95 latency | $ / request |",
           "|---|---|---|---|---|---|---|---|---|---|---|"]  # fmt: skip
    for s in ORDER:
        if s not in results:
            continue
        m = results[s]
        b = m["bands"]
        f1 = f"{m['f1']:.3f}" if m["f1"] is not None else "n/a"
        lat = (
            f"{m['p50']:.0f} / {m['p95']:.0f} ms" if m["p95"] >= 50 else f"{m['p50']:.1f} / {m['p95']:.1f} ms"
        )
        out.append(f"| {s} | {m['n']} | {pct(m['accuracy'])} | {pct(m['precision'])} | {pct(m['recall'])} | {f1} | "
                   f"{pct(m['fm_links'])} | {pct(m['fm_auto'])} | {b['auto']}/{b['suggest']}/{b['new']}/{b['failed']} | "
                   f"{lat} | {m['cost']:.4f} |")  # fmt: skip
    return out


def _wrong(ds: list[Decision], threshold: float) -> int:
    return sum(d.score >= threshold and d.predicted != d.expected for d in ds)


def _right(r: Row) -> bool:
    return bool(r["band"] != "failed" and r["predicted"] == r["expected"])


def main() -> None:
    report: list[str] = []
    data: dict[str, Any] = {}
    per_split: dict[str, dict[str, list[Row]]] = {}
    for split in ("dev", "test"):
        rows = load(split)
        rows["baseline"] = baseline_rows(split)
        per_split[split] = rows
        results = {s: summarize(r) for s, r in rows.items()}
        data[split] = results
        report += [*table(results, f"{split} (n = {results['baseline']['n']})"), ""]
    test = per_split["test"]
    for tag, title in (("handwritten", "test: Robert's handwritten cases"), ("paraphrase", "test: paraphrase slice"),
                       ("same_solution_different_need", "test: same solution, different need"),
                       ("different_solution_same_need", "test: different solution, same need"),
                       ("hard_negative", "test: hard negatives"), ("new_need", "test: new needs")):  # fmt: skip
        res = {s: summarize([r for r in rows if tag in r["tags"]]) for s, rows in test.items()}
        report += [*table(res, title), ""]
    report += ["**Prompt injection** (test: 2 cases; dev: R07). A hijack is an auto-link to a wrong need.", "",
               "| Strategy | Right decision | Hijacks |", "|---|---|---|"]  # fmt: skip
    for s in ORDER:
        if s not in test:
            continue
        inj = [r for r in test[s] if "prompt_injection" in r["tags"]] + [
            r for r in per_split["dev"][s] if r["ref"] == "R07"
        ]
        hijack = sum(r["band"] == "auto" and r["predicted"] != r["expected"] for r in inj)
        report.append(
            f"| {s} | {pct(Rate(sum(_right(r) for r in inj), len(inj)))} | {hijack} of {len(inj)} |"
        )
    report.append("")
    report += ["**Calibration on test: accuracy by routing-score bucket** (the baseline's score is its similarity)", "",
               "| Strategy | " + " | ".join(f"[{lo:.1f}, {hi:.1f}{']' if hi == 1.0 else ')'}" for lo, hi in pairwise(BUCKETS)) + " |",
               "|---|" + "---|" * (len(BUCKETS) - 1)]  # fmt: skip
    for s in ORDER:
        if s in data["test"]:
            report.append(
                f"| {s} | "
                + " | ".join(pct(r) if r.n else "-" for _, _, r in data["test"][s]["buckets"])
                + " |"
            )
    report.append("")
    # T_auto: lowest routing score with dev precision >= 0.97 on >= 10 links, confirmed on test
    report += ["**Auto-link threshold on the routing score** (chosen on dev: lowest score with precision ≥ 0.97 on ≥ 10 links; confirmed on test)", "",
               "| Strategy | T_auto (dev) | lowest same_need score on dev | dev precision at T | test precision at T | test coverage of true duplicates | unreviewed false merges on test at T / at 0.90 |",
               "|---|---|---|---|---|---|---|"]  # fmt: skip
    thresholds: dict[str, float | None] = {}
    for s in ORDER[1:]:
        if s not in test:
            continue
        raw_dev = [
            Decision(r["expected"], r["top_need"], r["top_score"])
            for r in per_split["dev"][s]
            if r["top_need"]
        ]
        raw_test = [Decision(r["expected"], r["top_need"], r["top_score"]) for r in test[s] if r["top_need"]]
        t = choose_auto(raw_dev)
        thresholds[s] = t
        lowest = min((d.score for d in raw_dev), default=None)
        if t is None:
            report.append(f"| {s} | none reaches it | {lowest} | - | - | - | - |")
            continue
        dev_auto, test_auto = [d for d in raw_dev if d.score >= t], [d for d in raw_test if d.score >= t]
        dups = sum(r["expected"] is not None for r in test[s])
        report.append(
            f"| {s} | {t:.4f} | {lowest:.4f} | {pct(Rate(sum(d.predicted == d.expected for d in dev_auto), len(dev_auto)))} | "
            f"{pct(Rate(sum(d.predicted == d.expected for d in test_auto), len(test_auto)))} | "
            f"{pct(Rate(sum(d.predicted == d.expected for d in test_auto), dups))} | {_wrong(raw_test, t)} / {_wrong(raw_test, 0.90)} |"
        )
    report.append("")
    data["thresholds"] = thresholds
    # cascade: decided on dev, confirmed on test
    lines = [
        "**Cascade check** (decided on dev, confirmed on test; the cascade sends Haiku's suggest band to Sonnet 5.5)",
        "",
    ]
    data["cascade"] = {}
    for split in ("dev", "test"):
        rows = per_split[split]
        if not all(k in rows for k in ("haiku", "sonnet", "sonnet-low")):
            continue
        h, so = ({r["ref"]: r for r in rows[k]} for k in ("haiku", "sonnet"))
        conf = [x for x, r in h.items() if r["band"] == "auto"]
        gray = [x for x, r in h.items() if r["band"] == "suggest"]
        new_misses = sum(r["band"] == "new" and not _right(r) for r in h.values())
        casc = summarize(cascade_rows(h, so))
        slow = data[split]["sonnet-low"]
        lines += [
            f"- **{split}.** On Haiku's confident cases (auto band, n = {len(conf)}): Haiku {pct(Rate(sum(_right(h[x]) for x in conf), len(conf)))}, "
            f"Sonnet {pct(Rate(sum(_right(so[x]) for x in conf), len(conf)))}. "
            f"On the band a cascade would escalate (suggest, n = {len(gray)}): Haiku {pct(Rate(sum(_right(h[x]) for x in gray), len(gray)))}, "
            f"Sonnet {pct(Rate(sum(_right(so[x]) for x in gray), len(gray)))}. "
            f"{new_misses} of Haiku's misses sit in its new band, which a cascade never escalates. "
            f"Cascade: accuracy {pct(casc['accuracy'])}, ${casc['cost']:.4f}/request; sonnet-low: {pct(slow['accuracy'])}, ${slow['cost']:.4f}/request; "
            f"haiku alone: {pct(data[split]['haiku']['accuracy'])}, ${data[split]['haiku']['cost']:.4f}/request."
        ]  # fmt: skip
        data["cascade"][split] = {
            "summary": casc,
            "confident": len(conf),
            "gray": len(gray),
            "new_misses": new_misses,
        }
    report += [*lines, ""]
    (RESULTS / "comparison.md").write_text("\n".join(report) + "\n", encoding="utf-8")
    (RESULTS / "comparison.json").write_text(
        json.dumps(data, default=lambda o: o.__dict__ if hasattr(o, "__dict__") else str(o), indent=1)
    )
    print("\n".join(report))


if __name__ == "__main__":
    main()
