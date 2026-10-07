"""Stage 1 of dedupe (ADR 0002): find the candidate needs for a text.

Every request is indexed on its own, plus one canonical vector per need. A need scores its best
match: averaging three phrasings would land between them and match none well. Search is brute-force
cosine in numpy, which takes milliseconds at the backlog size we design for (ADR 0005).
"""

from dataclasses import dataclass

import numpy as np

from app.ai.embeddings import Embedder, Vectors


@dataclass(frozen=True)
class Hit:
    need_id: str
    score: float  # best cosine similarity between the query and any vector of this need
    via: str  # the request ref or "canonical" that gave the best match


class NeedIndex:
    def __init__(self, embedder: Embedder) -> None:
        self.embedder = embedder
        self._needs: list[str] = []
        self._via: list[str] = []
        self._rows: list[Vectors] = []
        self._matrix: Vectors | None = None

    def __len__(self) -> int:
        return len(self._needs)

    def _add(self, need_id: str, via: str, text: str) -> None:
        row = self.embedder.embed([text])[0]  # embed first: the three lists only ever change together
        self._needs.append(need_id)
        self._via.append(via)
        self._rows.append(row)
        self._matrix = None

    def add_request(self, ref: str, need_id: str, text: str) -> None:
        self._add(need_id, ref, text)

    def add_canonical(self, need_id: str, text: str) -> None:
        self._add(need_id, "canonical", text)

    def refs(self) -> set[str]:
        return set(self._via)

    def reassign(self, via: str, need_id: str) -> None:
        """Point an indexed request at another need (unlink, merge). Its vector stays the same."""
        for i, v in enumerate(self._via):
            if v == via:
                self._needs[i] = need_id

    def search(self, text: str, k: int = 5) -> list[Hit]:
        if not self._needs:
            return []
        if self._matrix is None:
            self._matrix = np.vstack(self._rows)
        sims = self._matrix @ self.embedder.embed([text])[0]
        best: dict[str, tuple[float, str]] = {}
        for need_id, via, sim in zip(self._needs, self._via, sims.tolist(), strict=True):
            if need_id not in best or sim > best[need_id][0]:
                best[need_id] = (sim, via)
        ranked = sorted(best.items(), key=lambda item: (-item[1][0], item[0]))
        return [Hit(need_id, score, via) for need_id, (score, via) in ranked[:k]]
