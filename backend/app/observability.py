"""Structured logs and request IDs (production readiness).

Every HTTP request gets an ID: the caller's X-Request-ID if it is safe, else a new one. It is returned in the
response, stored on the request row (Request.trace_id), restored by the worker when it processes that row,
and written on every AIRun, so one ID ties a submission to its queue processing and its model calls.
Logs are one JSON object per line, and pass through the same redaction as model inputs, plus secret patterns.
"""

import json
import logging
import re
import sys
import time
import uuid
from contextvars import ContextVar
from typing import Any, ClassVar

from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.ai.redact import redact

request_id: ContextVar[str | None] = ContextVar("request_id", default=None)
_SAFE_ID = re.compile(r"^[A-Za-z0-9._:-]{8,64}$")
SECRET = re.compile(
    r"sk-ant-[A-Za-z0-9_-]{10,}|sk-[A-Za-z0-9]{32,}|gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}"
    r"|AKIA[0-9A-Z]{16}|xox[abposr]-[A-Za-z0-9-]{10,}|(?i:bearer)\s+[A-Za-z0-9._~+/=-]{16,}"
)
_STANDARD = set(vars(logging.LogRecord("", 0, "", 0, "", (), None))) | {"message", "asctime"}


def scrub(text: str) -> str:
    """No secrets and no emails or phone numbers in logs (CLAUDE.md rule 9)."""
    return redact(SECRET.sub("[REDACTED]", text))


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        line: dict[str, Any] = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(record.created))
            + f".{int(record.msecs):03d}Z",
            "level": record.levelname,
            "logger": record.name,
            "msg": scrub(record.getMessage()),
            "request_id": request_id.get(),
        }
        for key, value in vars(
            record
        ).items():  # structured extras, e.g. log.info("...", extra={"status": 200})
            if key not in _STANDARD and key not in line:
                line[key] = scrub(value) if isinstance(value, str) else value
        if record.exc_info:
            line["error"] = scrub(self.formatException(record.exc_info))
        return json.dumps(line, default=str)


class TextFormatter(logging.Formatter):
    """Readable lines for local work, scrubbed like the JSON ones."""

    def format(self, record: logging.LogRecord) -> str:
        return scrub(f"{record.levelname} {record.name} [{request_id.get() or '-'}] {super().format(record)}")


def configure_logging(fmt: str = "json", level: str = "INFO") -> None:
    """One redacting handler on the root logger. Uvicorn's own handlers are removed so its logs pass through
    it too, and its access log (which prints query strings, i.e. what users type) is silenced: RequestContext
    writes the access log without them. Idempotent."""
    root = logging.getLogger()
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        lg = logging.getLogger(name)
        lg.handlers.clear()
        lg.propagate = True
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    if any(getattr(h, "_distill", False) for h in root.handlers):
        return
    handler = logging.StreamHandler(sys.stdout)
    handler._distill = True  # type: ignore[attr-defined]
    handler.setFormatter(JsonFormatter() if fmt == "json" else TextFormatter("%(message)s"))
    root.addHandler(handler)
    root.setLevel(level)


def new_id() -> str:
    return uuid.uuid4().hex


class RequestContext:
    """ASGI middleware: request ID in and out, security headers, and one access-log line per request
    (method, path without the query string, status, duration; never bodies or query text)."""

    HEADERS: ClassVar[list[tuple[bytes, bytes]]] = [
        (b"x-content-type-options", b"nosniff"),
        (b"x-frame-options", b"DENY"),
        (b"referrer-policy", b"no-referrer"),
        (b"cache-control", b"no-store"),  # responses carry customer data
    ]

    def __init__(self, app: ASGIApp) -> None:
        self.app = app
        self.log = logging.getLogger("distill.access")

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        incoming = dict(scope.get("headers") or []).get(b"x-request-id", b"").decode("latin-1")
        rid = incoming if _SAFE_ID.match(incoming) else new_id()
        token = request_id.set(rid)
        started, status = time.perf_counter(), 500

        async def send_with_headers(message: Message) -> None:
            nonlocal status
            if message["type"] == "http.response.start":
                status = message["status"]
                message.setdefault("headers", [])
                message["headers"] = [*message["headers"], (b"x-request-id", rid.encode()), *self.HEADERS]
            await send(message)

        try:
            await self.app(scope, receive, send_with_headers)
        finally:
            path = scope["path"][:256]  # a long path can't make logging expensive
            self.log.info(
                "%s %s %s",
                scope["method"],
                path,
                status,
                extra={"method": scope["method"], "path": path, "status": status,
                       "duration_ms": round((time.perf_counter() - started) * 1000, 1)},
            )  # fmt: skip
            request_id.reset(token)


class CatchAll:
    """Innermost middleware: an unhandled exception becomes our 500 here, inside CORS and RequestContext, so
    the response keeps the request ID, the security headers and CORS, and the log line has the request ID.
    Internals are logged, never returned."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app
        self.log = logging.getLogger("distill")

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        started = False

        async def tracked(message: Message) -> None:
            nonlocal started
            started = started or message["type"] == "http.response.start"
            await send(message)

        try:
            await self.app(scope, receive, tracked)
        except Exception:
            self.log.exception("Unhandled error on %s %s", scope["method"], scope["path"][:256])
            if started:
                raise
            body = json.dumps(
                {"error": {"code": "internal_error", "message": "Internal server error", "details": []}}
            )
            await send({"type": "http.response.start", "status": 500,
                        "headers": [(b"content-type", b"application/json"), (b"content-length", str(len(body)).encode())]})  # fmt: skip
            await send({"type": "http.response.body", "body": body.encode()})
