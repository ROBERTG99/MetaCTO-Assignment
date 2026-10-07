"""Eval metrics. Pure functions over Decision records; every number in REPORT.md comes from here."""

import math
from dataclasses import dataclass, field
from itertools import pairwise


@dataclass(frozen=True)
class Decision:
    """One routing decision. `None` means "new need" for both expected and predicted."""

    expected: str | None
    predicted: str | None
    score: float = 0.0
    band: str = "new"  # auto | suggest | new
    candidates: tuple[str, ...] = field(default_factory=tuple)  # retrieved needs, best first
    latency_ms: float = 0.0


@dataclass(frozen=True)
class Rate:
    k: int
    n: int

    @property
    def value(self) -> float | None:
        return self.k / self.n if self.n else None

    @property
    def interval(self) -> tuple[float, float]:
        return wilson(self.k, self.n)


@dataclass(frozen=True)
class PRF:
    precision: Rate
    recall: Rate
    f1: float | None


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    """Wilson score interval for k successes in n trials (95% by default). No data: (0, 1)."""
    if n == 0:
        return (0.0, 1.0)
    p = k / n
    denom = 1 + z * z / n
    center = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return (max(0.0, center - half), min(1.0, center + half))


def decision_accuracy(ds: list[Decision]) -> Rate:
    """Right link to the expected need, or "new" when a new need was expected."""
    return Rate(sum(d.predicted == d.expected for d in ds), len(ds))


def duplicate_prf(ds: list[Decision]) -> PRF:
    """Duplicates as the positive class. A link to the wrong need is both a false positive and a miss."""
    true_pos = sum(d.predicted is not None and d.predicted == d.expected for d in ds)
    precision = Rate(true_pos, sum(d.predicted is not None for d in ds))
    recall = Rate(true_pos, sum(d.expected is not None for d in ds))
    p, r = precision.value, recall.value
    f1 = None if p is None or r is None or p + r == 0 else 2 * p * r / (p + r)
    return PRF(precision, recall, f1)


def false_merge_rate(ds: list[Decision]) -> Rate:
    """Of the links made: linked to the wrong need, or linked when it should have been new."""
    linked = [d for d in ds if d.predicted is not None]
    return Rate(sum(d.predicted != d.expected for d in linked), len(linked))


def recall_at_k(ds: list[Decision], k: int) -> Rate:
    """Of the cases whose need already exists: is it among the first k retrieved needs?"""
    known = [d for d in ds if d.expected is not None]
    return Rate(sum(d.expected in d.candidates[:k] for d in known), len(known))


def accuracy_by_bucket(ds: list[Decision], edges: list[float]) -> list[tuple[float, float, Rate]]:
    """Decision accuracy per score bucket [lo, hi); the last bucket also includes its upper edge.

    Scores are clamped to the edges first, so float noise (1.0000001) never drops a decision.
    """
    buckets = []
    clamped = [(min(max(d.score, edges[0]), edges[-1]), d) for d in ds]
    for i, (lo, hi) in enumerate(pairwise(edges)):
        last = i == len(edges) - 2
        inside = [d for score, d in clamped if lo <= score < hi or (last and score == hi)]
        buckets.append((lo, hi, decision_accuracy(inside)))
    return buckets


def percentile(values: list[float], q: float) -> float:
    """Nearest-rank percentile: the smallest observed value with at least q of the data at or below it."""
    if not values:
        raise ValueError("percentile of an empty list")
    ordered = sorted(values)
    rank = max(1, math.ceil(q * len(ordered)))
    return ordered[rank - 1]
