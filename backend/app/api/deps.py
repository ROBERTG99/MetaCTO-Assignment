"""FastAPI dependency for the AI and config dependencies built in the lifespan (app.state.deps)."""

from fastapi import Request

from app.ai.pipeline import Deps


def get_deps(request: Request) -> Deps:
    deps: Deps = request.app.state.deps
    return deps
