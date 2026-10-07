"""The snapshot builder only reads the cache: a miss is reported and nothing is written."""

from pathlib import Path

import pytest
from app.ai.embeddings import FakeEmbedder

import evals.snapshot as snap


def test_a_cache_miss_is_reported_and_nothing_is_written(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(snap, "CACHE_FILE", tmp_path / "empty.jsonl")
    monkeypatch.setattr(snap, "OUT", tmp_path / "snapshot.json")
    monkeypatch.setattr(snap, "FastEmbedder", lambda **_k: FakeEmbedder())
    out = snap.build()
    assert out.get("misses") and all("extract" in m for m in out["misses"][:3])
    assert snap.main() == 2
    assert not (tmp_path / "snapshot.json").exists()
    assert not (tmp_path / "empty.jsonl").exists() or (tmp_path / "empty.jsonl").read_text() == ""
