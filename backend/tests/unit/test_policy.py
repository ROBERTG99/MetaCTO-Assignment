"""Routing is computed in code from the label, the similarity and field agreement (ADR 0003)."""

from pathlib import Path

import pytest

from app.ai.policy import (
    RoutingConfig,
    Scored,
    claim_confirmed,
    decide,
    in_audit_sample,
    load_routing,
    routing_score,
)

CFG = RoutingConfig(w_label=0.5, w_sim=0.3, w_fields=0.2, s_min=0.2, s_max=0.8, auto=0.9, suggest=0.6)


@pytest.mark.parametrize(
    ("label", "sim", "area", "persona", "expected"),
    [
        ("same_need", 0.8, True, True, 1.0),  # 0.5 + 0.3*1 + 0.2*1
        ("same_need", 0.2, False, False, 0.5),  # 0.5 + 0 + 0
        ("same_need", 0.5, True, False, 0.75),  # 0.5 + 0.3*0.5 + 0.2*0.5
        ("same_need", 0.95, True, True, 1.0),  # similarity clipped at s_max
        ("same_need", 0.0, True, True, 0.7),  # clipped at s_min: 0.5 + 0 + 0.2
        ("related", 0.8, True, True, 0.0),  # only same_need can route to a link
        ("different", 0.8, True, True, 0.0),
    ],
)
def test_routing_score(label: str, sim: float, area: bool, persona: bool, expected: float) -> None:
    assert routing_score(label, sim, area, persona, CFG) == pytest.approx(expected)


def s(need: int, score: float, label: str = "same_need") -> Scored:
    return Scored(need, label, 0.5, True, True, score)


@pytest.mark.parametrize(
    ("scored", "band", "need"),
    [
        ([s(1, 0.95), s(2, 0.99)], "auto", 2),  # best score wins
        ([s(1, 0.90)], "auto", 1),  # auto is inclusive
        ([s(1, 0.8999)], "suggest", 1),
        ([s(1, 0.60)], "suggest", 1),  # suggest is inclusive
        ([s(1, 0.5999)], "new", None),
        ([s(1, 0.0, "different"), s(2, 0.0, "related")], "new", None),
        ([], "new", None),
    ],
)
def test_bands(scored: list[Scored], band: str, need: int | None) -> None:
    route = decide(scored, CFG)
    assert (route.band, route.need_id) == (band, need)


def test_audit_sample_is_about_ten_percent_and_repeatable() -> None:
    cfg = RoutingConfig(audit_rate=0.10, audit_seed="seed-a")
    picked = {i for i in range(1, 2001) if in_audit_sample(i, cfg)}
    assert 160 <= len(picked) <= 240  # 10% of 2000, give or take
    assert picked == {i for i in range(1, 2001) if in_audit_sample(i, cfg)}  # same seed, same sample
    other = {
        i for i in range(1, 2001) if in_audit_sample(i, RoutingConfig(audit_rate=0.10, audit_seed="seed-b"))
    }
    assert other != picked
    assert not any(in_audit_sample(i, RoutingConfig(audit_rate=0.0)) for i in range(1, 200))
    assert all(in_audit_sample(i, RoutingConfig(audit_rate=1.0)) for i in range(1, 200))


def test_claim_is_confirmed_only_by_same_need_at_or_above_suggest() -> None:
    assert claim_confirmed(s(1, 0.60), CFG)
    assert not claim_confirmed(s(1, 0.59), CFG)
    assert not claim_confirmed(s(1, 0.0, "different"), CFG)
    assert not claim_confirmed(None, CFG)


def test_routing_config_loads_the_llm_section(tmp_path: Path) -> None:
    p = tmp_path / "routing.yaml"
    p.write_text(
        "baseline: {auto: 0.7, suggest: 0.6}\n"
        "llm:\n  weights: {label: 0.5, similarity: 0.3, fields: 0.2}\n  similarity: {s_min: 0.5, s_max: 0.9}\n"
        "  thresholds: {auto: 0.92, suggest: 0.61}\n  audit: {rate: 0.1, seed: x}\n  top_k: 4\n"
    )
    cfg = load_routing(p)
    assert (cfg.auto, cfg.suggest, cfg.s_min, cfg.s_max, cfg.top_k, cfg.audit_seed) == (
        0.92,
        0.61,
        0.5,
        0.9,
        4,
        "x",
    )


@pytest.mark.parametrize(
    ("sim", "area", "persona"), [(0.62, True, False), (0.80, True, True), (0.70, False, False)]
)
def test_similarity_is_recovered_from_a_score_when_it_was_not_clipped(
    sim: float, area: bool, persona: bool
) -> None:
    from app.ai.policy import similarity_from_score

    cfg = RoutingConfig(w_label=0.5, w_sim=0.3, w_fields=0.2, s_min=0.55, s_max=0.85, auto=0.7, suggest=0.6,
                        audit_rate=0.1, audit_seed="t", top_k=5)  # fmt: skip
    score = routing_score("same_need", sim, area, persona, cfg)
    assert similarity_from_score("same_need", score, area, persona, cfg) == pytest.approx(sim)
    clipped = routing_score("same_need", 0.95, area, persona, cfg)  # above s_max: the exact value is lost
    assert similarity_from_score("same_need", clipped, area, persona, cfg) is None
    assert similarity_from_score("related", 0.0, area, persona, cfg) is None
