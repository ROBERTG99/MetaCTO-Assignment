"""Embedder interface (ADR 0002): local fastembed bge-small in the app, a deterministic fake in tests.

The model is downloaded once by `make setup` into the cache directory. After that it loads with
`local_files_only`, so offline mode never touches the network.
"""

import hashlib
import re
import sys
from pathlib import Path
from typing import Protocol

import numpy as np
from numpy.typing import NDArray

from app.config import get_settings

Vectors = NDArray[np.float32]


class Embedder(Protocol):
    model_name: str
    dim: int

    def embed(self, texts: list[str]) -> Vectors:
        """One L2-normalised float32 row per text."""
        ...


def _normalise(rows: Vectors) -> Vectors:
    norms = np.linalg.norm(rows, axis=1, keepdims=True)
    return (rows / np.where(norms == 0, 1, norms)).astype(np.float32)


class FastEmbedder:
    """BAAI/bge-small-en-v1.5 (384 dims, English, MIT) through fastembed's ONNX runtime."""

    def __init__(
        self, model_name: str | None = None, cache_dir: Path | None = None, download: bool = False
    ) -> None:
        from fastembed import TextEmbedding

        settings = get_settings()
        self.model_name = model_name or settings.embedding_model
        cache = cache_dir or Path(settings.embedding_cache_dir)
        if not cache.is_absolute():  # relative to backend/, wherever the process was started
            cache = Path(__file__).resolve().parents[2] / cache
        try:
            self._model = TextEmbedding(self.model_name, cache_dir=str(cache), local_files_only=not download)
        except Exception as exc:  # fastembed raises plain exceptions when the files are missing
            raise RuntimeError(
                f"Embedding model {self.model_name} is not in {cache}. Run `make setup`."
            ) from exc
        self.dim = int(self.embed(["dimension probe"]).shape[1])

    def embed(self, texts: list[str]) -> Vectors:
        return _normalise(np.array(list(self._model.embed(texts)), dtype=np.float32))


class FakeEmbedder:
    """Deterministic bag-of-words hashing. Shares words means similar; nothing else. For tests only."""

    model_name, dim = "fake-hash-64", 64

    def embed(self, texts: list[str]) -> Vectors:
        rows = np.zeros((len(texts), self.dim), dtype=np.float32)
        for i, text in enumerate(texts):
            for word in re.findall(r"[a-z0-9]+", text.lower()):
                rows[i, int(hashlib.md5(word.encode()).hexdigest(), 16) % self.dim] += 1.0
        return _normalise(rows)


def main() -> None:
    """`python -m app.ai.embeddings download`: fetch the model into the cache (used by make setup)."""
    if sys.argv[1:] != ["download"]:
        raise SystemExit("usage: python -m app.ai.embeddings download")
    embedder = FastEmbedder(download=True)
    print(
        f"Embedding model ready: {embedder.model_name} ({embedder.dim} dims) in {get_settings().embedding_cache_dir}"
    )


if __name__ == "__main__":
    main()
