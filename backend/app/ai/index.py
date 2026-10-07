"""The in-process vector index over the database (ADR 0005): rebuilt at startup, updated on every write.

Requests are indexed on their redacted text under their need; each need adds its title (problem plus
persona) as the canonical vector. Merged needs are left out, so they never come back as candidates.
"""

import threading

from sqlmodel import Session, col, select

from app.ai.embeddings import Embedder
from app.ai.retrieval import NeedIndex
from app.models import Need, NeedStatus, Request


def request_text(r: Request) -> str:
    return r.redacted_text or f"{r.title}\n{r.description}"


class NeedSearch:
    """Thread-safe: the worker thread and the API threads share it, so every read and write takes the lock."""

    def __init__(self, embedder: Embedder) -> None:
        self.embedder = embedder
        self.index = NeedIndex(embedder)
        self._lock = threading.RLock()

    def rebuild(self, session: Session) -> None:
        fresh = NeedIndex(self.embedder)  # built aside, then swapped in
        live = {n.id: n for n in session.exec(select(Need).where(Need.status != NeedStatus.merged)).all()}
        for r in session.exec(select(Request).where(col(Request.need_id).is_not(None))).all():
            if r.need_id is not None and r.need_id in live and r.id is not None:
                fresh.add_request(f"r{r.id}", str(r.need_id), request_text(r))
        for need in live.values():
            fresh.add_canonical(str(need.id), need.title)
        with self._lock:
            self.index = fresh

    def add_request(self, request_id: int, need_id: int, text: str) -> None:
        with self._lock:
            self.index.add_request(f"r{request_id}", str(need_id), text)

    def move_request(self, request_id: int, need_id: int, text: str) -> None:
        """Point the request at another need; index it first if it wasn't linked before."""
        with self._lock:
            if f"r{request_id}" in self.index.refs():
                self.index.reassign(f"r{request_id}", str(need_id))
            else:
                self.index.add_request(f"r{request_id}", str(need_id), text)

    def add_need(self, need: Need) -> None:
        if need.id is not None:
            with self._lock:
                self.index.add_canonical(str(need.id), need.title)

    def search(self, text: str, k: int = 5) -> list[tuple[int, float]]:
        with self._lock:
            return [(int(h.need_id), h.score) for h in self.index.search(text, k)]
