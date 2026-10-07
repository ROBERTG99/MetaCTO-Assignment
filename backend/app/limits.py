"""Abuse limits for a public intake: a body size cap, a per-client budget on every write, and a tighter
per-client rate on the public writes (submit, support), each of which becomes paid model calls.

The public rate is a dependency on the two routes, so it applies to the matched route however the path is
spelled (/needs/+1/support is still /needs/{need_id}/support). The write budget applies to every POST, PUT
and PATCH by method, so no path escapes it. In memory and per process, which is right for this
single-process deployment (ADR 0005); several API processes need a shared store (README "Production path").
"""

import json
import time
from collections import defaultdict, deque
from collections.abc import Callable
from dataclasses import dataclass

from fastapi import Request
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.errors import AppError, error_body


@dataclass(frozen=True)
class Limits:
    posts_per_minute: int = 30  # per client, on POST /requests and POST /needs/{id}/support each
    writes_per_minute: int = 120  # per client, on every write
    max_body_bytes: int = 64_000
    web_origins: tuple[str, ...] = ("http://localhost:5173", "http://127.0.0.1:5173")


class RateLimiter:
    """Sliding window: at most `limit` events per `window` seconds per key. Empty keys are dropped."""

    def __init__(self, limit: int, window: float = 60.0, clock: Callable[[], float] = time.monotonic) -> None:
        self.limit, self.window, self.clock = limit, window, clock
        self.events: dict[str, deque[float]] = defaultdict(deque)
        self._sweep_at = 0.0

    def hit(self, key: str) -> float | None:
        """None if allowed (and counted); otherwise the seconds until the next event is allowed."""
        now = self.clock()
        if now >= self._sweep_at:  # bounded memory: forget clients idle for a whole window
            for k in [k for k, q in self.events.items() if not q or q[-1] <= now - self.window]:
                del self.events[k]
            self._sweep_at = now + self.window
        q = self.events[key]
        while q and q[0] <= now - self.window:
            q.popleft()
        if len(q) >= self.limit:
            return q[0] + self.window - now
        q.append(now)
        return None


def client_of(scope: Scope) -> str:
    """The socket peer; behind a proxy, run uvicorn with --forwarded-allow-ips=<proxy> so this is the client."""
    return str((scope.get("client") or ("unknown", 0))[0])


def public_write(request: Request) -> None:
    """Route dependency for the public writes: 429 over the per-client rate for this route."""
    limiter: RateLimiter = request.app.state.public_limiter
    route = getattr(request.scope.get("route"), "path", request.url.path)
    wait = limiter.hit(f"{client_of(request.scope)}:{route}")
    if wait is not None:
        raise AppError(429, "rate_limited", "Too many submissions; try again shortly",
                       headers={"Retry-After": str(max(1, int(wait) + 1))})  # fmt: skip


class _TooLarge(Exception):
    pass


async def _reply(
    send: Send, status: int, code: str, message: str, headers: list[tuple[bytes, bytes]]
) -> None:
    body = json.dumps(error_body(code, message)).encode()
    await send({"type": "http.response.start", "status": status,
                "headers": [(b"content-type", b"application/json"), (b"content-length", str(len(body)).encode()), *headers]})  # fmt: skip
    await send({"type": "http.response.body", "body": body})


class LimitsMiddleware:
    """Writes only: 411 without a length, 413 over the cap (declared, or while streaming), 429 over the
    per-client write budget. Answers in the API's error shape."""

    def __init__(self, app: ASGIApp, limits: Limits) -> None:
        self.app, self.limits = app, limits
        self.writes = RateLimiter(limits.writes_per_minute)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope["method"] not in ("POST", "PUT", "PATCH"):
            await self.app(scope, receive, send)
            return
        cap = self.limits.max_body_bytes
        headers = dict(scope.get("headers") or [])
        length = headers.get(b"content-length")
        if length is None and b"chunked" in headers.get(b"transfer-encoding", b"").lower():
            await _reply(
                send, 411, "length_required", "Send a Content-Length (chunked bodies aren't accepted)", []
            )
            return
        if length is not None and length.isdigit() and int(length) > cap:
            await _reply(send, 413, "payload_too_large", f"Request body is over {cap} bytes", [])
            return
        wait = self.writes.hit(client_of(scope))
        if wait is not None:
            await _reply(send, 429, "rate_limited", "Too many changes; try again shortly",
                         [(b"retry-after", str(max(1, int(wait) + 1)).encode())])  # fmt: skip
            return
        seen, started = 0, False

        async def counted() -> Message:
            nonlocal seen
            message = await receive()
            if message["type"] == "http.request":
                seen += len(message.get("body", b""))
                if seen > cap:
                    raise _TooLarge
            return message

        async def tracked(message: Message) -> None:
            nonlocal started
            started = started or message["type"] == "http.response.start"
            await send(message)

        try:
            await self.app(scope, counted, tracked)
        except _TooLarge:
            if not started:
                await _reply(send, 413, "payload_too_large", f"Request body is over {cap} bytes", [])
