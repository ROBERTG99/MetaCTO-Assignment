"""The test set is valid, frozen, and the freeze cannot be bypassed by editing one file."""

import json
import shutil
import subprocess
from collections import Counter
from pathlib import Path

import pytest

from evals.dataset import DATASETS, FrozenError, check_frozen, load_cases, sha256_of


def test_test_set_matches_the_schema_and_the_brief() -> None:
    cases = load_cases(DATASETS / "test.jsonl")
    assert len(cases) == 150
    assert len({c.id for c in cases}) == 150
    slices: Counter[str] = Counter(c.slice for c in cases)
    assert slices["prompt_injection"] == 2 and slices["non_english"] >= 3
    hard = ("same_solution_different_need", "different_solution_same_need", "hard_negative", "paraphrase")
    assert sum(slices[s] for s in hard) >= 90  # weighted toward the hard cases
    assert all(c.reviewed_by_human == c.id.startswith("H") for c in cases)


def test_handwritten_cases_are_in_the_test_set_unchanged() -> None:
    test_lines = (DATASETS / "test.jsonl").read_text(encoding="utf-8").splitlines()
    hand = [
        line
        for line in (DATASETS / "test_handwritten.jsonl").read_text(encoding="utf-8").splitlines()
        if line
    ]
    assert hand and test_lines[: len(hand)] == hand


def test_every_expected_need_exists_in_the_seed_backlog() -> None:
    truth = json.loads(
        (DATASETS.parents[1] / "backend" / "seed" / "ground_truth.json").read_text(encoding="utf-8")
    )
    for c in load_cases(DATASETS / "test.jsonl"):
        assert c.expected.need is None or c.expected.need in truth["needs"], c.id
        assert set(c.expected.must_not_link) <= set(truth["needs"]), c.id
        assert c.expected.need not in c.expected.must_not_link, c.id


def test_the_committed_test_set_is_frozen() -> None:
    assert check_frozen() == (DATASETS / "FROZEN").read_text().split()[0]


def git(repo: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True)


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    data = tmp_path / "datasets"
    data.mkdir()
    shutil.copy(DATASETS / "test.jsonl", data / "test.jsonl")
    (data / "FROZEN").write_text(f"{sha256_of(data / 'test.jsonl')}  test.jsonl\n")
    git(tmp_path, "init", "-q")
    git(tmp_path, "-c", "user.email=t@t", "-c", "user.name=t", "add", "datasets")
    git(tmp_path, "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-q", "-m", "freeze")
    return data


def commit(data: Path, *files: str) -> None:
    root = data.parent
    git(root, "add", *[f"datasets/{f}" for f in files])
    git(root, "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-q", "-m", "change")


def edit_case(data: Path) -> None:
    with (data / "test.jsonl").open("a", encoding="utf-8") as f:
        f.write(
            (DATASETS / "test.jsonl").read_text(encoding="utf-8").splitlines()[0].replace("H001", "H999")
            + "\n"
        )


def refreeze(data: Path) -> None:
    (data / "FROZEN").write_text(f"{sha256_of(data / 'test.jsonl')}  test.jsonl\n")


def test_frozen_repo_passes(repo: Path) -> None:
    assert check_frozen(repo) == sha256_of(repo / "test.jsonl")


def test_refuses_an_edited_test_set(repo: Path) -> None:
    edit_case(repo)
    with pytest.raises(FrozenError, match="does not match"):
        check_frozen(repo)


def test_refuses_an_uncommitted_refreeze(repo: Path) -> None:
    edit_case(repo)
    refreeze(repo)
    with pytest.raises(FrozenError, match="uncommitted"):
        check_frozen(repo)


def test_refuses_a_refreeze_in_a_different_commit(repo: Path) -> None:
    edit_case(repo)
    commit(repo, "test.jsonl")
    refreeze(repo)
    commit(repo, "FROZEN")
    with pytest.raises(FrozenError, match="same commit"):
        check_frozen(repo)


def test_accepts_a_change_committed_together_with_its_hash(repo: Path) -> None:
    edit_case(repo)
    refreeze(repo)
    commit(repo, "test.jsonl", "FROZEN")
    assert check_frozen(repo) == sha256_of(repo / "test.jsonl")


def test_an_empty_frozen_file_is_a_clean_refusal(repo: Path) -> None:
    (repo / "FROZEN").write_text("")
    with pytest.raises(FrozenError, match="empty"):
        check_frozen(repo)
