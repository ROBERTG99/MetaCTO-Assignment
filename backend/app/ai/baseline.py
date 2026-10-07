"""The no-LLM strategy: route on the top retrieval similarity alone. Also the app's offline mode.

It runs the same three bands as the LLM policy (ADR 0004), with similarity in place of the routing
score, so the comparison in evals/REPORT.md is like for like. Thresholds are tuned on dev only.
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import yaml

from app.ai.retrieval import Hit

Band = Literal["auto", "suggest", "new"]


@dataclass(frozen=True)
class Thresholds:
    auto: float
    suggest: float


@dataclass(frozen=True)
class Routed:
    band: Band
    need_id: str | None
    score: float


def route(hits: list[Hit], th: Thresholds) -> Routed:
    if not hits:
        return Routed("new", None, 0.0)
    best = hits[0]
    if best.score >= th.auto:
        return Routed("auto", best.need_id, best.score)
    if best.score >= th.suggest:
        return Routed("suggest", best.need_id, best.score)
    return Routed("new", None, best.score)


def load_thresholds(path: Path) -> Thresholds:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))["baseline"]
    th = Thresholds(auto=float(data["auto"]), suggest=float(data["suggest"]))
    if th.suggest > th.auto:
        raise ValueError(f"suggest ({th.suggest}) must not be above auto ({th.auto})")
    return th
