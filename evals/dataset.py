"""Eval cases (schema in datasets/case.schema.json) and the test-set freeze."""

import hashlib
import subprocess
import sys
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

DATASETS = Path(__file__).resolve().parent / "datasets"
TEST_FILE, FROZEN_FILE = "test.jsonl", "FROZEN"

Slice = Literal[
    "same_solution_different_need",
    "different_solution_same_need",
    "hard_negative",
    "paraphrase",
    "clear_duplicate",
    "new_need",
    "prompt_injection",
    "non_english",
]


class FrozenError(RuntimeError):
    """The test set changed without its hash being updated in the same commit."""


class CaseRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1, max_length=200)
    description: str = Field(max_length=5000)
    requester_role: str
    segment: Literal["enterprise", "mid_market", "smb", "prospect", "internal"]
    source: Literal["portal", "support", "sales", "cs", "internal"]

    @property
    def text(self) -> str:
        return f"{self.title}\n{self.description}"


class Expected(BaseModel):
    model_config = ConfigDict(extra="forbid")

    need: str | None
    persona: str
    must_not_link: list[str] = []


class Case(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(pattern=r"^(H|T)[0-9]{3}$")
    slice: Slice
    backlog: Literal["seed_v1"]
    request: CaseRequest
    expected: Expected
    rationale: str = Field(min_length=1)
    author: str
    reviewed_by_human: bool


def load_cases(path: Path) -> list[Case]:
    lines = path.read_text(encoding="utf-8").splitlines()
    return [Case.model_validate_json(line) for line in lines if line.strip()]


def sha256_of(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _git(cwd: Path, *args: str) -> str | None:
    try:
        out = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return out.stdout.strip() if out.returncode == 0 else None


def check_frozen(datasets: Path = DATASETS) -> str:
    """Return the hash if test.jsonl is frozen; raise FrozenError otherwise.

    Frozen means: the file's SHA-256 equals the one in FROZEN, neither file has uncommitted changes,
    and the last commit that touched test.jsonl also touched FROZEN. Outside a git checkout, or in a shallow
    clone, only the hash is checked (with a warning). A later commit that touches only FROZEN locks the runner
    out until test.jsonl and FROZEN are committed together again: it fails closed on purpose.
    """
    test, frozen = datasets / TEST_FILE, datasets / FROZEN_FILE
    fields = frozen.read_text(encoding="utf-8").split() if frozen.exists() else []
    if not fields:
        raise FrozenError(f"{FROZEN_FILE} is missing or empty; freeze the test set first.")
    actual, recorded = sha256_of(test), fields[0]
    if actual != recorded:
        raise FrozenError(
            f"{TEST_FILE} does not match its frozen hash ({actual[:12]} vs {recorded[:12]}). "
            "The test set is frozen: change it only on purpose, with FROZEN updated in the same commit."
        )
    if _git(datasets, "rev-parse", "--is-inside-work-tree") != "true":
        print(
            "warning: not a usable git checkout; only the hash of the test set was checked", file=sys.stderr
        )
        return actual
    if _git(datasets, "status", "--porcelain", "--", TEST_FILE, FROZEN_FILE):
        raise FrozenError(
            f"{TEST_FILE} or {FROZEN_FILE} has uncommitted changes; commit them together first."
        )
    if _git(datasets, "rev-parse", "--is-shallow-repository") == "true":
        # depth-1 clones (CI) can't show which commit touched what; the hash check above still holds
        print("warning: shallow clone; the same-commit rule was not checked", file=sys.stderr)
        return actual
    last_test = _git(datasets, "log", "-1", "--format=%H", "--", TEST_FILE)
    last_frozen = _git(datasets, "log", "-1", "--format=%H", "--", FROZEN_FILE)
    if last_test != last_frozen:
        raise FrozenError(f"The last change to {TEST_FILE} was not in the same commit as {FROZEN_FILE}.")
    return actual
