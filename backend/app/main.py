"""FastAPI application factory. The lifespan creates tables, builds the AI dependencies and the vector index,
reclaims stale queue claims, and starts the worker loop (ADR 0007)."""

import asyncio
import contextlib
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from sqlalchemy.engine import Engine
from sqlmodel import Session

from app import errors
from app.ai.pipeline import Deps
from app.api import insights, metrics, needs, requesters, requests, triage
from app.db import create_tables, get_engine
from app.worker import Worker


def _log_worker_exit(task: "asyncio.Task[None]") -> None:
    if not task.cancelled() and task.exception() is not None:
        logging.getLogger("distill.worker").error("worker loop stopped", exc_info=task.exception())


def create_app(engine: Engine | None = None, deps: Deps | None = None, start_worker: bool = True) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        create_tables(app.state.engine)
        if app.state.deps is None:
            from app.ai.factory import build_deps  # real embedder and gateway per AI_MODE

            app.state.deps = build_deps(app.state.engine)
        with Session(app.state.engine) as session:
            app.state.deps.search.rebuild(session)
        worker = Worker(app.state.engine, app.state.deps)
        app.state.worker = worker
        task = None
        if app.state.start_worker:
            worker.reclaim_stale(lease_seconds=0)  # one worker: anything in processing was interrupted
            task = asyncio.create_task(worker.run_forever())
            task.add_done_callback(_log_worker_exit)
        yield
        if task is not None:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task

    app = FastAPI(title="Distill API", version="0.1.0", lifespan=lifespan)
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
    return app


app = create_app()
