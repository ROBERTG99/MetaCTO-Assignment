"""The fake is deterministic and normalised; the real model loads offline and ranks a paraphrase first."""

import socket
from pathlib import Path

import numpy as np
import pytest

from app.ai.embeddings import FakeEmbedder, FastEmbedder
from app.config import get_settings

CACHE = Path(__file__).resolve().parents[2] / get_settings().embedding_cache_dir


def test_fake_embedder_is_deterministic_and_normalised() -> None:
    e = FakeEmbedder()
    a, b = e.embed(["SSO with Okta", "sso with okta!"]), e.embed(["SSO with Okta"])
    assert a.shape == (2, 64) and a.dtype == np.float32
    assert np.allclose(np.linalg.norm(a, axis=1), 1.0)
    assert np.allclose(a[0], a[1]) and np.allclose(a[0], b[0])


@pytest.fixture(scope="module")
def real() -> FastEmbedder:
    if not CACHE.exists():
        pytest.skip("embedding model not downloaded; run `make setup`")
    return FastEmbedder(cache_dir=CACHE)


def test_real_model_loads_from_the_cache_without_network(
    real: FastEmbedder, monkeypatch: pytest.MonkeyPatch
) -> None:
    def no_network(*_args: object, **_kwargs: object) -> None:
        raise OSError("network access attempted in offline mode")

    monkeypatch.setattr(socket.socket, "connect", no_network)
    monkeypatch.setattr(socket, "create_connection", no_network)
    fresh = FastEmbedder(cache_dir=CACHE)
    assert fresh.dim == 384 and fresh.embed(["offline"]).shape == (1, 384)


def test_real_model_ranks_a_paraphrase_above_an_unrelated_text(real: FastEmbedder) -> None:
    q, para, other = real.embed([
        "Let us log in with our Okta accounts",
        "Single sign-on through our identity provider",
        "Dark theme for late nights",
    ])  # fmt: skip
    assert float(q @ para) > float(q @ other) + 0.1
