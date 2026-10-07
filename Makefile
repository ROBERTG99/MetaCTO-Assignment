.PHONY: setup dev-api test lint typecheck check check-hooks seed openapi eval-offline eval-tune eval

BACKEND := cd backend &&

# Install backend dependencies (Python 3.12 via uv)
setup:
	$(BACKEND) uv sync && uv run python -m app.ai.embeddings download

# API on :8000 with reload
dev-api:
	$(BACKEND) uv run uvicorn app.main:app --reload --port 8000

test:
	$(BACKEND) uv run pytest

lint:
	$(BACKEND) uv run ruff check . ../evals && uv run ruff format --check . ../evals

typecheck:
	$(BACKEND) uv run mypy

# Full gate: lint, types, tests, hook tests
check: lint typecheck test check-hooks

# Claude Code hook tests, with the project's ruff on PATH so the formatter tests run instead of skip
check-hooks:
	PATH="$(CURDIR)/backend/.venv/bin:$$PATH" HOOK_TESTS_REQUIRE_RUFF=1 python3 -m unittest discover -s .claude/hooks -v

# Reset the local database and load the raw Brightboard seed (no needs, all requests pending)
seed:
	$(BACKEND) uv run python -m seed.load

# Write backend/openapi.json without starting the server
openapi:
	$(BACKEND) uv run python -m app.openapi

# Evals. Offline runs are free: no model calls.
SPLIT ?= dev
STRATEGY ?= baseline
EVAL := cd backend && PYTHONPATH=.. HF_HUB_OFFLINE=1 uv run python -m evals.run

eval-offline:
	$(EVAL) --split $(SPLIT) --strategy $(STRATEGY)

# Choose baseline thresholds on dev only and write config/routing.yaml
eval-tune:
	$(EVAL) --split dev --tune

# Paid LLM strategies: not built yet
eval:
	@echo "make eval runs the paid LLM strategies, which don't exist yet. Use make eval-offline." && exit 1
