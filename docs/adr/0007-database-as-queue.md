# 0007. The database as the queue

Status: accepted, 2026-10-07

## Context
CLAUDE.md rule 2: a submission is saved before any model call, enrichment runs in the background, and a provider failure sends the request to needs_review with a reason. FastAPI BackgroundTasks lose work on restart, which leaves requests stuck in processing forever: a silent failure. Redis or Celery would add infrastructure and break the one-command offline run (D5).

## Decision
- **The request row is the job.** `POST /requests` saves the request as `pending` and returns 201. Nothing else has to be written for it to be processed.
- **Queue fields on the row:** `status` (pending, processing, processed, needs_review), `attempts`, `last_error`, `claimed_at`.
- **The worker loop.** It starts in FastAPI's lifespan, claims the oldest pending row, sets it `processing` with `claimed_at = now`, and increments `attempts`.
- **Transient errors** (provider errors, timeouts): the row goes back to `pending`, with `last_error` recorded. It becomes eligible again when `claimed_at + backoff(attempts) <= now` (backoff 5 s × 2^attempts), so no extra column is needed.
- **Terminal failures** move the row to `needs_review` with the reason, with no further retries. They are: a refusal; a second max_tokens or validation failure (the gateway retries each once itself); and a transient error on the Nth attempt (default 3).
- **Stale claims.** On startup, and periodically, `processing` rows whose `claimed_at` is older than the lease (default 300 s) go back to `pending`.
- **No partial state.** Results (AI fields, need_id, suggestions, LinkEvents) are written in one transaction with `status = processed`, so a retry is idempotent.
- **Claims use the same loop.** Supports in `claimed` state are checked by it too, with their own `check_attempts`, `check_started_at` and `check_error`, under the same lease and backoff rules. A terminal failure sets the support to `disputed` with a `review_reason`, so it lands in the Disputed claims tab instead of staying `claimed` forever.
- **Testable without timing.** `worker.run_once()` processes one row, so tests drive the worker deterministically.
- Revised on 2026-10-07: the first version used a separate `job` table. Robert's decision (f) was "new requests are saved as pending; the worker claims rows", and a separate table adds a second state to keep in sync for no gain at this size.

## Alternatives rejected
- **FastAPI BackgroundTasks.** Loses work on restart, has no retries, and can't be observed.
- **Redis with RQ or Celery.** Durable, but adds a service, a Docker dependency and setup time.
- **Synchronous processing in the request.** Breaks "AI never blocks a submission".

## Consequences
- In the offline demo, a submission is processed within seconds, and the UI polls the request's status.
- One worker, one process: throughput is limited, which is acceptable at this volume (ADR 0005). The same worker code can run as its own process when we move to Postgres.
- The request table also gives queue metrics (pending depth, attempts, needs_review) for the AI Ops view.
- If briefs (should) need the queue, they get their own status columns on their own table, following the same pattern.
