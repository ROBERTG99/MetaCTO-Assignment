import logging
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from sqlmodel import Session

from app import health

router = APIRouter(tags=["health"])
log = logging.getLogger("distill.health")


@router.get("/healthz", summary="Liveness: the process answers")
def healthz() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/readyz", summary="Readiness: database, AI dependencies and worker, plus queue depth and stuck claims",
            responses={503: {"description": "Not ready"}})  # fmt: skip
def readyz(request: Request) -> JSONResponse:
    app = request.app
    checks: dict[str, str] = {}
    queue: dict[str, Any] | None = None
    try:
        health.ping_database(app.state.engine)
        with Session(app.state.engine) as s:
            queue = health.queue_stats(s)
        checks["database"] = "ok"
    except Exception:
        log.exception("readiness: database check failed")
        checks["database"] = "error"
    checks["ai"] = "ok" if app.state.deps is not None else "error"
    task = getattr(app.state, "worker_task", None)
    if app.state.start_worker:
        checks["worker"] = "ok" if task is not None and not task.done() else "error"
    ready = all(v == "ok" for v in checks.values())
    body = {"status": "ready" if ready else "not_ready", "checks": checks, "queue": queue}
    return JSONResponse(body, status_code=200 if ready else 503)
