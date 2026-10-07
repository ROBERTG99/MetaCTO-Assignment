"""The seed is test data for evals and the demo, so it is tested like code."""

import json
from collections import Counter
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy.engine import Engine
from sqlmodel import Session, func, select

from app.models import Account, Need, Request, Requester, RequestStatus

SEED = Path(__file__).resolve().parents[2] / "seed"


def load(name: str) -> Any:
    return json.loads((SEED / name).read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def data() -> dict[str, Any]:
    return {n: load(f"{n}.json") for n in ("accounts", "requesters", "requests", "ground_truth")}


def test_every_request_is_labelled(data: dict[str, Any]) -> None:
    truth = data["ground_truth"]
    refs = [r["ref"] for r in data["requests"]]
    assert len(refs) == len(set(refs))
    assert set(refs) == set(truth["requests"])
    for ref, label in truth["requests"].items():
        assert label["persona"], ref
        if label["need"] is None:
            assert "noise" in label["tags"], f"{ref} has no need and is not marked noise"
        else:
            assert label["need"] in truth["needs"], f"{ref} points to unknown need {label['need']}"


def test_every_cluster_except_noise_has_at_least_two_members(data: dict[str, Any]) -> None:
    sizes = Counter(label["need"] for label in data["ground_truth"]["requests"].values() if label["need"])
    assert set(sizes) == set(data["ground_truth"]["needs"]), "a need in the truth file has no requests"
    assert {need: n for need, n in sizes.items() if n < 2} == {}


def test_every_referenced_account_and_requester_exists(data: dict[str, Any]) -> None:
    accounts = {a["ref"] for a in data["accounts"]}
    people = {p["ref"]: p for p in data["requesters"]}
    assert all(p["account"] is None or p["account"] in accounts for p in people.values())
    for r in data["requests"]:
        assert r["requester"] in people, r["ref"]
        assert r["account"] is None or r["account"] in accounts, r["ref"]
        if people[r["requester"]]["account"] is None:  # staff submit on behalf of a customer
            assert r["source"] in {"support", "sales", "cs", "internal"}, r["ref"]
            assert r["account"] is not None or r["source"] == "internal", r["ref"]


def test_excel_split_has_members_on_both_sides(data: dict[str, Any]) -> None:
    labels = data["ground_truth"]["requests"]
    texts = {r["ref"]: f"{r['title']} {r['description']}".lower() for r in data["requests"]}
    for need in ("excel_finance", "data_portability"):
        members = [ref for ref, label in labels.items() if label["need"] == need and "excel" in texts[ref]]
        assert len(members) >= 2, f"{need} needs at least two requests that say Excel, has {members}"
    personas = {
        need: {labels[ref]["persona"] for ref in labels if labels[ref]["need"] == need}
        for need in ("excel_finance", "data_portability")
    }
    assert "finance" in personas["excel_finance"] and "finance" not in personas["data_portability"]


def test_related_and_hard_negative_pairs_name_real_needs(data: dict[str, Any]) -> None:
    truth = data["ground_truth"]
    pairs = truth["related"] + truth["hard_negatives"]
    assert pairs
    for p in pairs:
        assert len(p["needs"]) == 2 and set(p["needs"]) <= set(truth["needs"]), p


def test_arrival_order_follows_the_days(data: dict[str, Any]) -> None:
    day = {r["ref"]: r["day"] for r in data["requests"]}
    order = data["ground_truth"]["arrival_order"]
    assert sorted(order) == sorted(day)
    assert [day[ref] for ref in order] == sorted(day.values())


def test_account_mix_and_sources_match_the_brief(data: dict[str, Any]) -> None:
    customers = [a for a in data["accounts"] if not a.get("is_prospect")]
    prospects = [a for a in data["accounts"] if a.get("is_prospect")]
    assert Counter(a["segment"] for a in customers) == {"enterprise": 3, "mid_market": 5, "smb": 4}
    assert len(prospects) == 3 and all(a["pipeline_value"] > 0 and a["arr"] == 0 for a in prospects)
    assert {r["source"] for r in data["requests"]} == {"portal", "support", "sales", "cs", "internal"}
    assert 55 <= len(data["requests"]) <= 65 and 14 <= len(data["ground_truth"]["needs"]) <= 18


def test_adversarial_cases_are_present(data: dict[str, Any]) -> None:
    tags = Counter(t for label in data["ground_truth"]["requests"].values() for t in label["tags"])
    assert {t: tags[t] for t in ("prompt_injection", "pii", "non_english", "noise")} == {
        "prompt_injection": 1,
        "pii": 1,
        "non_english": 1,
        "noise": 1,
    }
    pii = next(r for r in data["requests"] if "pii" in data["ground_truth"]["requests"][r["ref"]]["tags"])
    assert "@" in pii["description"] and "555" in pii["description"]


def test_loader_loads_raw_data_only(engine: Engine) -> None:
    from seed.load import load_seed

    counts = load_seed(engine)
    with Session(engine) as s:
        assert s.exec(select(func.count()).select_from(Account)).one() == counts["accounts"] == 15
        assert s.exec(select(func.count()).select_from(Requester)).one() == counts["requesters"]
        requests = s.exec(select(Request)).all()
        assert len(requests) == counts["requests"] == len(load("requests.json"))
        assert all(r.status == RequestStatus.pending and r.need_id is None for r in requests)
        assert all(r.account_id is not None for r in requests if r.source != "internal")
        assert s.exec(select(func.count()).select_from(Need)).one() == 0  # the truth is for evals, not the DB


def test_loader_is_repeatable(engine: Engine) -> None:
    from seed.load import load_seed

    first = load_seed(engine)
    assert load_seed(engine) == first
    with Session(engine) as s:
        assert s.exec(select(func.count()).select_from(Request)).one() == first["requests"]


def test_loader_applies_the_recorded_snapshot(engine: Engine) -> None:
    from app.models import AIRun, AISuggestion, LinkActor, LinkEvent, SuggestionKind
    from seed.load import load_seed

    snap = load("snapshot.json")
    counts = load_seed(engine, snapshot=True)
    with Session(engine) as s:
        requests = s.exec(select(Request)).all()
        assert all(r.status == RequestStatus.processed for r in requests)
        assert all(
            r.need_statement and r.persona and r.product_area for r in requests
        )  # real extraction on every row
        bands = Counter(d["decision"]["band"] for d in snap["requests"].values())
        linked = sum(r.need_id is not None for r in requests)
        assert linked == bands["auto"] + bands["new"]
        runs = s.exec(select(AIRun)).all()
        assert len(runs) == counts["ai_runs"] == sum(len(d["runs"]) for d in snap["requests"].values())
        assert {r.model for r in runs} == {"claude-haiku-4-5-20251001"} and all(r.cost_usd > 0 for r in runs)
        events = s.exec(select(LinkEvent)).all()
        assert len(events) == linked and all(e.actor == LinkActor.auto for e in events)
        auto = s.exec(select(AISuggestion).where(AISuggestion.kind == SuggestionKind.duplicate)).all()
        assert len(auto) == bands["auto"] + bands["suggest"]
        assert all(n.priority_score is not None for n in s.exec(select(Need)).all())


def test_a_tampered_snapshot_is_rejected(
    engine: Engine, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import seed.load as loader

    snap = load("snapshot.json")
    first = next(iter(snap["requests"]))
    snap["requests"][first]["extraction"]["product_area"] = "not-an-area"
    (tmp_path / "snapshot.json").write_text(json.dumps(snap))
    monkeypatch.setattr(loader, "SNAPSHOT", tmp_path / "snapshot.json")
    with pytest.raises(ValueError):
        loader.load_seed(engine, snapshot=True)


def test_the_committed_snapshot_matches_the_locked_config() -> None:
    from app.ai.policy import load_routing

    cfg = load_routing(SEED.parent.parent / "config" / "routing.yaml")
    snap = load("snapshot.json")
    assert snap["routing"] == {"auto": cfg.auto, "suggest": cfg.suggest, "s_min": cfg.s_min, "s_max": cfg.s_max,
                               "weights": [cfg.w_label, cfg.w_sim, cfg.w_fields]}  # fmt: skip
    assert snap["prompts"] == ["extract_need_v1", "adjudicate_v1"]


@pytest.mark.parametrize(
    "tamper",
    ["unknown_need_key", "bad_related_label", "auto_without_need", "stale_threshold"],
)
def test_an_inconsistent_snapshot_is_a_clear_error(
    engine: Engine, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, tamper: str
) -> None:
    import seed.load as loader

    snap = load("snapshot.json")
    auto_ref = next(r for r, d in snap["requests"].items() if d["decision"]["band"] == "auto")
    with_related = next(r for r, d in snap["requests"].items() if d["decision"]["related"])
    if tamper == "unknown_need_key":
        snap["requests"][auto_ref]["decision"]["need_key"] = "no-such-need"
    elif tamper == "bad_related_label":
        snap["requests"][with_related]["decision"]["related"][0]["label"] = "same"
    elif tamper == "auto_without_need":
        snap["requests"][auto_ref]["decision"]["need_key"] = None
    else:
        snap["routing"]["auto"] = 0.9
    (tmp_path / "snapshot.json").write_text(json.dumps(snap))
    monkeypatch.setattr(loader, "SNAPSHOT", tmp_path / "snapshot.json")
    with pytest.raises(ValueError):
        loader.load_seed(engine, snapshot=True)


def test_seeded_related_suggestions_carry_their_run_and_score(engine: Engine) -> None:
    from app.models import AISuggestion, SuggestionKind
    from seed.load import load_seed

    load_seed(engine, snapshot=True)
    with Session(engine) as s:
        related = s.exec(select(AISuggestion).where(AISuggestion.kind == SuggestionKind.related)).all()
        assert related and all(r.ai_run_id is not None and r.routing_score is not None for r in related)
        assert all(
            r.processed_at is not None and r.processed_at >= r.created_at
            for r in s.exec(select(Request)).all()
        )
