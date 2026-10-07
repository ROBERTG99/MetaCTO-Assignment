.PHONY: demo brief-live e2e-live test-web setup setup-backend setup-web audit eval-gate dev dev-api dev-web test lint typecheck typecheck-web check check-hooks e2e gen-api seed seed-raw seed-live openapi rank eval-offline eval-tune eval eval-compare eval-fit-report snapshot

BACKEND := cd backend &&

WEB := cd frontend &&

# Install backend (Python 3.12 via uv) and frontend (npm) dependencies, the embedding model and Playwright's Chromium
setup: setup-backend setup-web

setup-backend:
	$(BACKEND) uv sync && uv run python -m app.ai.embeddings download

setup-web:
	$(WEB) npm ci && npx playwright install chromium

# Known vulnerabilities in what ships: Python runtime dependencies (pip-audit) and npm production dependencies
audit:
	$(BACKEND) uv export --no-dev --format requirements-txt --no-emit-project > .audit-requirements.txt && uvx pip-audit==2.10.1 -r .audit-requirements.txt --disable-pip; rc=$$?; trash .audit-requirements.txt; exit $$rc
	$(WEB) npm audit --omit=dev --audit-level=high

# One command, offline and without a key: install, load the demo data, run API and web app
demo: setup seed dev

# API on :8000 (with its worker) and the web app on :5173
dev:
	$(MAKE) -j2 dev-api dev-web

# API on :8000 with reload
dev-api:
	$(BACKEND) uv run uvicorn app.main:app --reload --port 8000 --no-access-log

dev-web:
	$(WEB) npm run dev

# Regenerate the frontend's API types from backend/openapi.json (run make openapi first)
gen-api:
	$(WEB) npm run gen:api

typecheck-web:
	$(WEB) npm run typecheck

test-web:
	$(WEB) npm test

test:
	$(BACKEND) uv run pytest

lint:
	$(BACKEND) uv run ruff check . ../evals && uv run ruff format --check . ../evals

typecheck:
	$(BACKEND) uv run mypy

# Full gate: lint, types, tests, hook tests, frontend types and unit tests
check: lint typecheck test check-hooks typecheck-web test-web

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

# Paid: one live decision brief for the need whose title contains NEED, written to OUT. Needs Robert's go
# (CLAUDE.md); .claude/settings.json does not ask for it yet.
# Uses its own database (data/live.db), reset to the seed. Typically 3-9 agent turns on Haiku and 1-2 brief calls on Sonnet (worst case: 18 Haiku and 6 Sonnet calls, with every retry).
NEED ?= SAML SSO with Okta
OUT ?= ../docs/examples/brief-sso.md
brief-live:
	$(BACKEND) AI_MODE=live HF_HUB_OFFLINE=1 DATABASE_URL=sqlite:///./data/live.db uv run python -m seed.brief_live --need "$(NEED)" --out $(OUT)

# Free: print the priority ranking of the local database (PRIORITIES=path/to/priorities.yaml to try other weights)
rank:
	$(BACKEND) uv run python -m app.rank $(if $(PRIORITIES),--config $(abspath $(PRIORITIES)))

# Golden paths (frontend/e2e): a fresh offline API on :8001 (backend/data/e2e.db, reseeded) with its in-process
# worker, and the web app on :5174; Playwright starts and stops both. No API key, no network.
e2e:
	$(WEB) npx playwright test

# Paid: the same golden paths against the real API (AI_MODE=live). Needs Robert's go (CLAUDE.md); .claude/settings.json
# does not ask for it yet. It uses its own database (backend/data/e2e-live.db), so `make e2e` never overwrites
# the live ai_runs. About 14 model calls and $0.07 per run (REPORT §6).
e2e-live:
	$(WEB) E2E_AI_MODE=live npx playwright test --timeout=180000

# Write backend/openapi.json without starting the server
openapi:
	$(BACKEND) uv run python -m app.openapi

# Evals. Offline runs are free: no model calls.
SPLIT ?= dev
STRATEGY ?= baseline
EVAL := cd backend && PYTHONPATH=.. HF_HUB_OFFLINE=1 uv run python -m evals.run

eval-offline:
	$(EVAL) --split $(SPLIT) --strategy $(STRATEGY)

# Free regression gate (CI): the offline baseline on dev and test must stay above evals/gates.yaml
eval-gate:
	$(MAKE) eval-offline SPLIT=dev && $(MAKE) eval-offline SPLIT=test
	cd backend && PYTHONPATH=.. uv run python -m evals.gate

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
