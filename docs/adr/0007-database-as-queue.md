# 0007. The database as the queue

Status: accepted, 2026-10-07

## Context
CLAUDE.md rule 2: a submission is saved before any model call, enrichment runs in the background, and a provider failure sends the request to needs_review with a reason. FastAPI BackgroundTasks lose work on restart, which leaves requests stuck in processing forever: a silent failure. Redis or Celery would add infrastructure and break the one-command offline run (D5).

## Decision
- **One transaction.** `POST /requests` writes the request (pending) and a `job` row (queued) in the same transaction, so a saved request always has its job.
- **The worker loop.** It starts in FastAPI's lifespan, claims the oldest queued job whose `available_at` has passed, sets it running, and increments `attempts`.
- **Transient errors** (provider errors, timeouts): the job goes back to the queue with exponential backoff, and `last_error` is recorded.
- **Terminal failures** go straight to needs_review with the reason, and the job to failed, with no further retries. They are: a refusal; a second max_tokens or validation failure (the gateway retries each once itself); and a transient error on the Nth attempt (default 3). An active requester claim on that request becomes disputed.
- **Stale claims.** On startup, and periodically, running jobs older than the lease (default 300 s) go back to queued.
- **No partial state.** Results are written in one transaction at the end, so a retry is idempotent.
- **Testable without timing.** `worker.run_once()` processes a single job, so tests drive the worker deterministically, without sleeps or timing.
- Briefs (should) use the same queue with `kind=brief`.

## Alternatives rejected
- **FastAPI BackgroundTasks.** Loses work on restart, has no retries, and can't be observed.
- **Redis with RQ or Celery.** Durable, but adds a service, a Docker dependency and setup time.
- **Synchronous processing in the request.** Breaks "AI never blocks a submission".

## Consequences
- In the offline demo, a submission is processed within seconds, and the UI polls the request's status.
- One worker, one process: throughput is limited, which is acceptable at this volume (ADR 0005). The same worker code can run as its own process when we move to Postgres.
- The job table also gives queue metrics (depth, attempts, failures) for the AI Ops view.
