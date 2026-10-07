"""FastAPI application factory. The lifespan creates tables, builds the AI dependencies and the vector index,
reclaims stale queue claims, and starts the worker loop (ADR 0007)."""

import asyncio
import contextlib
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.engine import Engine
from sqlmodel import Session

from app import errors
from app.ai.pipeline import Deps
from app.api import health, insights, metrics, needs, portal, requesters, requests, triage, updates
from app.config import get_settings
from app.db import create_tables, get_engine
from app.limits import Limits, LimitsMiddleware, RateLimiter
from app.observability import CatchAll, RequestContext, configure_logging
from app.worker import Worker, WorkerConfig


def _log_worker_exit(task: "asyncio.Task[None]") -> None:
    if not task.cancelled() and task.exception() is not None:
        logging.getLogger("distill.worker").error("worker loop stopped", exc_info=task.exception())


def create_app(
    engine: Engine | None = None,
    deps: Deps | None = None,
    start_worker: bool = True,
    limits: Limits | None = None,
) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        create_tables(app.state.engine)
        if app.state.deps is None:
            from app.ai.factory import build_deps  # real embedder and gateway per AI_MODE

            app.state.deps = build_deps(app.state.engine)
        with Session(app.state.engine) as session:
            app.state.deps.search.rebuild(session)
        worker = Worker(
            app.state.engine, app.state.deps, WorkerConfig(daily_budget_usd=settings.daily_model_budget_usd)
        )
        app.state.worker = worker
        task = None
        if app.state.start_worker:
            worker.reclaim_stale(lease_seconds=0)  # one worker: anything in processing was interrupted
            task = asyncio.create_task(worker.run_forever())
            task.add_done_callback(_log_worker_exit)
        app.state.worker_task = task
        yield
        if task is not None:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task

    settings = get_settings()
    configure_logging(settings.log_format)
    limits = limits or Limits(
        posts_per_minute=settings.posts_per_minute,
        writes_per_minute=settings.writes_per_minute,
        max_body_bytes=settings.max_body_bytes,
        web_origins=tuple(o.strip() for o in settings.web_origins.split(",") if o.strip()),
    )
    docs = settings.docs_enabled  # off in production: no public map of the API
    app = FastAPI(title="Distill API", version="0.1.0", lifespan=lifespan, docs_url="/docs" if docs else None,
                  redoc_url="/redoc" if docs else None, openapi_url="/openapi.json" if docs else None)  # fmt: skip
    # Outermost last: request ID and headers on every response, CORS on errors too, limits before the app.
    app.state.public_limiter = RateLimiter(limits.posts_per_minute)
    app.add_middleware(CatchAll)  # innermost: a crash still gets CORS, the request ID and headers
    app.add_middleware(LimitsMiddleware, limits=limits)
    app.add_middleware(CORSMiddleware, allow_origins=list(limits.web_origins), allow_methods=["GET", "POST", "PATCH"],
                       allow_headers=["Content-Type", "X-Request-ID"], expose_headers=["X-Request-ID"])  # fmt: skip
    app.add_middleware(RequestContext)
    app.state.engine = engine if engine is not None else get_engine()
    app.state.deps = deps
    app.state.start_worker = start_worker
    errors.install(app)
    app.include_router(requests.router)
    app.include_router(needs.router)
    app.include_router(triage.router)
    app.include_router(insights.router)
    app.include_router(requesters.router)
    app.include_router(metrics.router)
    app.include_router(updates.router)
    app.include_router(health.router)
    app.include_router(portal.router)
    return app


app = create_app()
