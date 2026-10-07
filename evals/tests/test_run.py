"""Runner logic on a five-request fixture: dev labels, noise, raw tuning mode, and counting each case once."""

import json
from pathlib import Path

import pytest
from app.ai.baseline import Thresholds
from app.ai.embeddings import FakeEmbedder

from evals.dataset import Case
from evals.run import overall, replay_dev, run_test, seeded_backlog

TH = Thresholds(auto=0.9, suggest=0.3)


@pytest.fixture
def seed(tmp_path: Path) -> Path:
    requests = [
        {"ref": "R1", "title": "SSO with Okta", "description": "okta single sign on"},
        {"ref": "R2", "title": "Dark mode please", "description": "dark theme at night"},
        {"ref": "R3", "title": "Okta SSO login", "description": "okta single sign on for staff"},
        {"ref": "R4", "title": "make it better", "description": "clunky"},
        {"ref": "R5", "title": "Dark theme", "description": "dark mode at night"},
    ]
    truth = {
        "needs": {
            "sso": {"title": "IT admins need single sign on with Okta"},
            "dark": {"title": "Users want dark mode"},
        },
        "requests": {
            "R1": {"need": "sso"},
            "R2": {"need": "dark"},
            "R3": {"need": "sso"},
            "R4": {"need": None},
            "R5": {"need": "dark"},
        },
        "arrival_order": ["R1", "R2", "R3", "R4", "R5"],
    }
    (tmp_path / "requests.json").write_text(json.dumps(requests))
    (tmp_path / "ground_truth.json").write_text(json.dumps(truth))
    return tmp_path


def test_dev_labels_first_appearances_repeats_and_noise(seed: Path) -> None:
    tagged = replay_dev(FakeEmbedder(), TH, seed)
    assert [(t, d.expected) for t, d in tagged] == [
        ("first_appearance", None),  # R1 starts sso
        ("first_appearance", None),  # R2 starts dark
        ("repeat", "sso"),  # R3
        ("first_appearance", None),  # R4 noise: always expected new
        ("repeat", "dark"),  # R5
    ]
    assert tagged[0][1].candidates == ()  # the backlog starts empty
    assert "new:R4" in tagged[4][1].candidates  # noise became its own need, as a PM would create one
    assert len(overall(tagged, "dev")) == 5


def test_raw_mode_keeps_the_top_candidate_for_tuning(seed: Path) -> None:
    tagged = replay_dev(FakeEmbedder(), None, seed)
    r3 = tagged[2][1]
    assert (r3.band, r3.predicted) == ("raw", "sso") and r3.score > 0.5


def test_test_backlog_has_canonicals_and_no_noise(seed: Path) -> None:
    hits = seeded_backlog(FakeEmbedder(), seed).search("make it better clunky", k=5)
    assert {h.need_id for h in hits} == {"sso", "dark"}


def case(cid: str, need: str | None, title: str) -> Case:
    return Case.model_validate({
        "id": cid, "slice": "paraphrase", "backlog": "seed_v1",
        "request": {"title": title, "description": "", "requester_role": "x", "segment": "smb", "source": "portal"},
        "expected": {"need": need, "persona": "x"}, "rationale": "x", "author": "x",
        "reviewed_by_human": cid.startswith("H"),
    })  # fmt: skip


def test_each_test_case_counts_once_overall_and_once_per_origin(seed: Path) -> None:
    tagged = run_test(
        FakeEmbedder(), TH, [case("H001", "sso", "okta sso"), case("T001", "dark", "dark mode")], seed
    )
    assert sorted(t for t, _ in tagged) == ["generated", "handwritten", "paraphrase", "paraphrase"]
    assert [d.expected for d in overall(tagged, "test")] == ["sso", "dark"]
