"""The model judges, code decides (ADR 0003, ADR 0004): routing score, bands, audit sample, claim verdict."""

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import yaml

Band = Literal["auto", "suggest", "new"]


@dataclass(frozen=True)
class RoutingConfig:
    w_label: float = 0.5
    w_sim: float = 0.3
    w_fields: float = 0.2
    s_min: float = 0.55
    s_max: float = 0.85
    auto: float = 0.90
    suggest: float = 0.60
    audit_rate: float = 0.10
    audit_seed: str = "distill-audit-v1"
    top_k: int = 5


@dataclass(frozen=True)
class Scored:
    need_id: int
    label: str
    similarity: float
    area_match: bool
    persona_match: bool
    score: float


@dataclass(frozen=True)
class Route:
    band: Band
    need_id: int | None
    score: float


def load_routing(path: Path) -> RoutingConfig:
    llm = yaml.safe_load(path.read_text(encoding="utf-8"))["llm"]
    w, sim, th, audit = llm["weights"], llm["similarity"], llm["thresholds"], llm["audit"]
    return RoutingConfig(
        w_label=float(w["label"]),
        w_sim=float(w["similarity"]),
        w_fields=float(w["fields"]),
        s_min=float(sim["s_min"]),
        s_max=float(sim["s_max"]),
        auto=float(th["auto"]),
        suggest=float(th["suggest"]),
        audit_rate=float(audit["rate"]),
        audit_seed=str(audit["seed"]),
        top_k=int(llm.get("top_k", 5)),
    )


def routing_score(
    label: str, similarity: float, area_match: bool, persona_match: bool, cfg: RoutingConfig
) -> float:
    """0 unless the model says same_need; otherwise label weight + normalised similarity + field agreement."""
    if label != "same_need":
        return 0.0
    span = cfg.s_max - cfg.s_min
    sim = min(1.0, max(0.0, (similarity - cfg.s_min) / span)) if span > 0 else float(similarity >= cfg.s_max)
    fields = (int(area_match) + int(persona_match)) / 2
    return cfg.w_label + cfg.w_sim * sim + cfg.w_fields * fields


def decide(scored: list[Scored], cfg: RoutingConfig) -> Route:
    """The best same_need candidate by routing score, then the bands. Ties go to the lower need id."""
    best = max(
        (c for c in scored if c.label == "same_need"), key=lambda c: (c.score, -c.need_id), default=None
    )
    if best is None or best.score < cfg.suggest:
        return Route("new", None, best.score if best else 0.0)
    return Route("auto" if best.score >= cfg.auto else "suggest", best.need_id, best.score)


def in_audit_sample(request_id: int, cfg: RoutingConfig) -> bool:
    """A seeded hash of the id: about audit_rate of auto-links, the same ones on every run."""
    digest = hashlib.sha256(f"{cfg.audit_seed}:{request_id}".encode()).hexdigest()
    return int(digest, 16) % 10_000 < round(cfg.audit_rate * 10_000)


def claim_confirmed(claimed: Scored | None, cfg: RoutingConfig) -> bool:
    return claimed is not None and claimed.label == "same_need" and claimed.score >= cfg.suggest
