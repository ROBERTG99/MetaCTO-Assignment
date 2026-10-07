# Distill

AI-first feature intelligence for a product team: unstructured feature requests in, deduplicated, need-centric and prioritized decisions out, with a PM in the loop. Built for the MetaCTO technical assessment ([docs/assignment.md](docs/assignment.md)). Work in progress: the backend, the AI layer, the requester portal and the PM workspace (triage, priorities, need detail, AI Ops) and stakeholder updates (AI drafts, a code commitment check, PM approval) exist and pass the golden-path specs.

- What and why: [docs/spec.md](docs/spec.md) · Architecture: [docs/architecture.md](docs/architecture.md) · Decisions: [docs/adr/](docs/adr/)
- Evals: [evals/REPORT.md](evals/REPORT.md) · Requirements traceability: [docs/requirements.md](docs/requirements.md)
- How AI was used to build it: [prompts.txt](prompts.txt) (every prompt, logged by hooks) and [CLAUDE.md](CLAUDE.md)

## Run it

```bash
make setup      # uv sync, the local embedding model (bge-small, 64 MB), npm ci and Playwright's Chromium
make seed       # reset the local SQLite DB to the Brightboard seed, with recorded Haiku 4.5 output (seed/snapshot.json)
make dev        # FastAPI on :8000 with its worker, and the web app on :5173 (AI_MODE=offline by default: no API key needed)
make check      # ruff, mypy, pytest, hook tests, frontend typecheck
make e2e        # Playwright golden paths against a fresh offline API (:8001) and web app (:5174)
make eval-gate  # free offline eval on the baseline, checked against evals/gates.yaml (CI runs it)
make audit      # pip-audit and npm audit on what ships
```

`make seed` is real Haiku 4.5 output, replayed from the cached evals with no API calls: it splits 10 duplicates into needs of their own and links the vague "make it better" (R62) to an existing need, so the backlog has 27 needs where the ground truth has 17 (caveat in [evals/snapshot.py](evals/snapshot.py)). `make seed-raw` loads only the raw requests (no AI output). Evals: `make eval-offline` (free), `make eval-compare` (free, from cached replies), `make eval` and `make seed-live` (paid; they ask first). An API key goes in a repo-root `.env` (`ANTHROPIC_API_KEY=`), never in code or chat.

## The AI strategy, and what the threshold really is

Every request goes through an intake workflow: redact, embed, retrieve the 5 nearest needs, extract the underlying need, adjudicate against the candidates, then route in code. Both model steps run on **Haiku 4.5**: on the dev replay it overlaps Sonnet 5.5, so the simpler and cheaper model wins, and the frozen test set confirms it (91.3% vs 74.7%). Sonnet 5.5 with this prompt doesn't clearly beat the no-LLM baseline on accuracy (the intervals overlap), only on false merges. A stronger model wasn't automatically better ([REPORT §3](evals/REPORT.md)).

Routing uses a code-computed score, and a request auto-links at or above **T_auto = 0.6953**. To be plain about it:
- **The threshold is degenerate.** It equals the lowest score Haiku gives any same_need label on dev, so in practice *every same_need label auto-links*. The routing score doesn't separate Haiku's errors, and its weights are still placeholders.
- **The cost:** on test this means 3 false merges that no human reviews first, against 1 at 0.90. 0.90 would auto-link only 32% of true duplicates and send the rest to the PM, which defeats the point of the product.
- **The uncertainty:** the point estimate is 2.7%, inside the 3% target, but the 95% interval allows up to about 8%.
- **So the protection is the audit sample and undo, not the score.** 10% of auto-links go to the PM's Audit tab, which measures the real false-merge rate, and every link can be undone in one click.

## Limitations, and what would fix each one

| Limitation | Evidence | Fix |
|---|---|---|
| The data is synthetic: Brightboard, the seed and 133 of the 150 test cases were written by the team that built the system. | REPORT §1 | Real requests from a pilot, labelled by a PM who didn't build it. |
| Spanish (and any non-English) requests retrieve poorly: recall@1 is 1/4, because the embedding model, bge-small-en, is English-only. | REPORT §1, §3 | Evaluate a multilingual embedder (e.g. multilingual-e5-small in fastembed) on a Spanish slice of at least 20 cases, and switch if recall@5 holds. |
| Dev has no hard cases, so the threshold isn't stress-tested where it matters. The dev-tuned baseline failed on test exactly there. | REPORT §1, §3 | Write at least 25 hand-made hard cases for dev (same solution / different need, hard negatives), then choose T_auto again. |
| The adjudication prompt over-splits needs when the requester's persona differs from the need's: 11 of Haiku's 13 test misses. | REPORT §3, §4.4 | `adjudicate_v2` is proposed with ship criteria. It needs one eval run, about $0.80. |
| Two test labels are disputed (T050, T065). | REPORT §4.5 | A human decision, recorded as a new frozen test set (v2), never an edit of v1. |

## Production path

What would block this from going to production at a real client, ranked by risk. Estimates are for one engineer who knows the codebase. Fixed items were done in the "production hardening" step and are tested (`backend/tests/api/test_hardening_api.py`, `test_portal_api.py`) and run in CI.

### Still open

| # | Risk | Why it blocks | What to do | Estimate |
|---|---|---|---|---|
| 1 | **No authentication or authorization.** The role switcher lets anyone act as any requester or as a PM: approve messages to customers, change statuses, read the PM routes (accounts and ARR, request descriptions, the outbox, AI Ops). | Unauthorized access and external messages | OIDC SSO, with roles requester, PM and CS. Guard every route outside `/portal` as PM-only (the split is in place), and scope `/portal` reads and writes to the signed-in requester. | 2–3 days |
| 2 | **Single tenant.** | One client's data visible to another | A tenant id on every table, with row-level filtering. | 2 days |
| 3 | **SQLite, an in-process worker, no migrations, no backups.** `make seed` drops tables. | Data loss on deploy; one process only | Postgres with Alembic, the worker as its own process (`SELECT … FOR UPDATE SKIP LOCKED`), pgvector (ADR 0005), and backups with a restore drill. | 2–3 days |
| 4 | **Rate limits are in memory, per process.** | Limits multiply with replicas | A shared store (Redis) for the write budget and the public-write rate. Run uvicorn with `--forwarded-allow-ips=<proxy>`, so limits key on the real client and not the proxy. | 0.5 day |
| 5 | **Names and request text go to Anthropic** (emails and phones are redacted). | Needs a DPA and zero data retention, or name redaction | A DPA and ZDR, plus optional redaction of person names. | 0.5 day plus legal |
| 6 | **The outbox is simulated.** | Updates never reach customers | Email or Slack delivery from the outbox, with retries, bounces and unsubscribe. | 1–2 days |
| 7 | **No alerting or tracing.** Logs are JSON with request IDs, and `/readyz` exposes queue health, but nothing pages anyone. | Failures go unnoticed | Ship logs (e.g. Datadog), OpenTelemetry traces, alerts on stuck jobs, needs-review rate, spend and 5xx. | 1 day |
| 8 | **Evals missing:** `stakeholder_update_v1` has none; strategic-fit labels are waiting on a human; there are no injection slices for fit or updates. | Prompt quality unproven | Labelled cases for each, then the paid runs (about $1). | 0.5 day |
| 9 | **Internals are public:** `/metrics` and `/readyz` details, and the docs (off with `DOCS_ENABLED=false`). | Information leak | Serve `/readyz` details and `/metrics` on the internal network or behind PM auth. Turn docs off in production. | 1 hour |
| 10 | **No TLS or HSTS in the app.** | Transport security | Terminate TLS at the proxy and set HSTS there. | 1 hour |
| 11 | **Retention, deletion and export (GDPR).** | Compliance | Retention windows for ai_runs and requests, plus delete and export per person. | 1 day |
| 12 | **Capacity:** search is brute force up to about 10K needs (ADR 0005), and there is no load test. | A performance cliff | pgvector, a load test with k6, and an SLO. | 0.5 day |
| 13 | **Request IDs supplied by a client are trusted** (validated for format only). | Muddied traces | Trust the header only from the proxy, or prefix it with a server ID. | 30 min |
| 14 | **Polish:** accessibility audit, phone layout, one 515 kB JS bundle. | Quality | An audit, responsive fixes, and route-level code splitting. | 1 day |

### Fixed in the hardening step

| Risk | Fix |
|---|---|
| **Public writes unthrottled.** Each one becomes paid model calls. | **Per-client limits:** 30 per minute on `POST /requests` and `POST /needs/{id}/support`, matched by route so `/needs/+1/support` can't bypass it. A 120-per-minute budget covers every write by method. `429` responses carry `Retry-After`. |
| **Unbounded spend.** | The worker stops claiming jobs once today's model spend reaches `DAILY_MODEL_BUDGET_USD` (default $20). Jobs wait; nothing is lost. |
| **Request size.** | Every field is capped, and bodies are capped at 64 KB (`413`; `411` for chunked bodies). |
| **CORS and headers.** | CORS allows only `WEB_ORIGINS`. Every response, 500s included, has `nosniff`, `X-Frame-Options: DENY`, `Referrer-Policy: no-referrer` and `Cache-Control: no-store`. |
| **Secrets and PII in logs.** | JSON or text logs, both scrubbed of keys, emails and phones. Uvicorn's access log, which prints query text, is replaced by ours (method, path, status, duration). The email regex is linear time; it had been an O(n²) DoS through long URLs. |
| **No tracing.** | **Request IDs:** an `X-Request-ID` follows a submission through the queue onto its `ai_runs` (`Request.trace_id`, `AIRun.trace_id`). |
| **No health or queue visibility.** | `/healthz` and `/readyz` (database, AI dependencies, worker; `503` when not ready). Queue depth, stuck claims past the lease and pending background jobs appear in `/readyz` and on AI Ops. |
| **PM-only data in the requester portal.** | Requester pages read `/portal/...`, which has no revenue, accounts, request descriptions, other people's reasons, internal notes or audit trail. Requesters see a plain needs-review reason instead of internal errors. |
| **Repair turns echoed model output.** | Validation repairs send field locations and messages only. |
| **No CI or dependency checks.** | **CI** (`.github/workflows/ci.yml`, offline and free):<br>- ruff, strict mypy, pytest, the hook tests with ruff required;<br>- the offline eval gate (`evals/gates.yaml`);<br>- pip-audit and `npm audit` on production dependencies;<br>- the frontend typecheck and build;<br>- Playwright.<br>Actions are pinned to SHAs, and Dependabot runs weekly. |
