.PHONY: setup dev-api test lint typecheck check check-hooks seed seed-raw seed-live openapi rank eval-offline eval-tune eval eval-compare eval-fit-report snapshot

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

# Reset the local database and load the Brightboard seed with recorded Haiku 4.5 output (seed/snapshot.json)
seed:
	$(BACKEND) uv run python -m seed.load

# Raw seed only: pending requests, no AI output
seed-raw:
	$(BACKEND) uv run python -m seed.load --raw

# Paid: reset to the seed with a curated backlog and run REFS through the live pipeline (settings ask first).
# About 2 calls per request plus 1 strategic-fit call per need touched (see seed/live.py)
REFS ?= R22,R13,R07
seed-live:
	$(BACKEND) AI_MODE=live HF_HUB_OFFLINE=1 uv run python -m seed.live --refs $(REFS)

# Free: print the priority ranking of the local database (PRIORITIES=path/to/priorities.yaml to try other weights)
rank:
	$(BACKEND) uv run python -m app.rank $(if $(PRIORITIES),--config $(abspath $(PRIORITIES)))

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

# Paid (settings ask first). STEP=routing: LLM strategies on dev and test, cached in evals/results/llm_cache.jsonl.
# STEP=fit: strategic_fit_v1 on the seeded needs and the labelled cases, cached in evals/results/fit_cache.jsonl.
STEP ?= routing
STRATEGIES ?= haiku,sonnet,sonnet-low
eval:
ifeq ($(STEP),fit)
	cd backend && EVAL_ALLOW_PAID=1 PYTHONPATH=.. HF_HUB_OFFLINE=1 uv run python -m evals.fit --paid
else
	cd backend && EVAL_ALLOW_PAID=1 PYTHONPATH=.. HF_HUB_OFFLINE=1 uv run python -m evals.llm --strategies $(STRATEGIES)
endif

# Free: rebuild evals/results/strategic_fit.md and backend/seed/fit_snapshot.json from the fit cache (a miss writes nothing)
eval-fit-report:
	cd backend && PYTHONPATH=.. HF_HUB_OFFLINE=1 uv run python -m evals.fit

# Free: rebuild the strategy comparison (evals/results/comparison.md) from cached outcomes
eval-compare:
	cd backend && PYTHONPATH=.. HF_HUB_OFFLINE=1 uv run python -m evals.compare

# Free: rebuild backend/seed/snapshot.json from the cached Haiku dev replay (fails, writing nothing, on a cache miss)
snapshot:
	cd backend && PYTHONPATH=.. HF_HUB_OFFLINE=1 uv run python -m evals.snapshot
