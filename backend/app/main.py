"""FastAPI application factory."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from sqlalchemy.engine import Engine

from app import errors
from app.api import needs, requests
from app.db import create_tables, get_engine


def create_app(engine: Engine | None = None) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        create_tables(app.state.engine)
        yield

    app = FastAPI(title="Distill API", version="0.1.0", lifespan=lifespan)
    app.state.engine = engine if engine is not None else get_engine()
    errors.install(app)
    app.include_router(requests.router)
    app.include_router(needs.router)
    return app


app = create_app()
