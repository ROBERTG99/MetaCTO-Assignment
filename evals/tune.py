"""Choose baseline thresholds on the dev split only (docs/test-plan.md §3).

Each Decision carries the top retrieved need as `predicted` and its similarity as `score`, so one
replay gives every threshold's outcome.
"""

import math

from app.ai.baseline import Thresholds

from evals.metrics import Decision


def choose_auto(ds: list[Decision], min_precision: float = 0.97, min_links: int = 10) -> float | None:
    """The lowest score threshold whose auto-links reach the precision bar with enough volume.

    None means no threshold does: the baseline should not auto-link at all.
    """
    valid = []
    for t in sorted({d.score for d in ds}):
        linked = [d for d in ds if d.score >= t]
        right = sum(d.predicted == d.expected for d in linked)
        if len(linked) >= min_links and right / len(linked) >= min_precision:
            valid.append(t)
    return min(valid) if valid else None


def choose_suggest(ds: list[Decision], auto: float | None, keep: float = 0.95) -> float:
    """The highest threshold that still sends `keep` of the true duplicates left below auto to the inbox."""
    below = sorted(d.score for d in ds if d.expected is not None and (auto is None or d.score < auto))
    if not below:
        return auto if auto is not None else 1.0
    must_keep = math.ceil(keep * len(below))
    return below[len(below) - must_keep]


NEVER = 1.001  # above any cosine similarity: the baseline never auto-links


def choose_thresholds(
    ds: list[Decision], min_precision: float = 0.97, min_links: int = 10, keep: float = 0.95
) -> Thresholds:
    """Both thresholds, exactly as chosen. Not rounded: rounding can move an observed boundary score across."""
    auto = choose_auto(ds, min_precision, min_links)
    return Thresholds(auto=auto if auto is not None else NEVER, suggest=choose_suggest(ds, auto, keep))
