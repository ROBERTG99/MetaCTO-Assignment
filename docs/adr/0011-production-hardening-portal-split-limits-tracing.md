# 0011. Production hardening: a requester portal split, abuse limits, a spend ceiling, request IDs

Status: accepted, 2026-10-07

## Context
A security review of the whole repository found that the app was already sound on SQL, secrets and prompt-injection containment. What it lacked was what a real deployment needs on day one:
- the requester pages read PM data (ARR, request descriptions, other people's reasons);
- public writes were unthrottled, and each one turns into paid model calls;
- one long URL could stall the event loop through log redaction;
- no way to trace a submission into its model calls;
- no health or readiness endpoints;
- no CI.

Auth is out of scope for now (spec A3), so the design has to make adding it later simple.

## Decision
- **Two API surfaces.** `/portal/...` is what a requester may read. Every other route is PM-only by convention. Auth later guards by prefix, so a forgotten route fails closed rather than open.
- **Limits:**
  - **Public writes.** A per-client rate on the public writes (a route dependency, so path spellings can't bypass it).
  - **Every write.** A per-client budget on every write, by method.
  - **Body size.** A 64 KB body cap, and chunked bodies refused.
  - **Model spend.** A daily ceiling the worker checks before it claims a job, so jobs wait instead of spending. In memory, which is right for one process (ADR 0005); Redis is on the production path.
- **Tracing.** Every response carries an `X-Request-ID`. A submission's ID is stored on the row, restored by the worker, and written on each AIRun.
- **Logging.** Logs are JSON (or text locally), scrubbed of secrets, emails and phones. Our access log replaces uvicorn's, which printed query strings, and those carry what users type into search.
- **Health.** `/healthz` for liveness. `/readyz` checks the database, the AI dependencies and the worker, and reports queue depth and stuck claims. A catch-all inside CORS gives 500s the same headers and request ID as every other response.
- **CI runs offline and free:**
  - lint, strict types, tests, hook tests;
  - an eval gate on the baseline against committed floors;
  - dependency audits, the frontend build, Playwright.
  - Actions are pinned to SHAs.

## Alternatives rejected
- **Hiding PM fields in the requester UI only.** The browser would still receive them, and adding login later wouldn't fix it.
- **A rate limit on raw paths.** The review showed `/needs/+1/support` bypassing it.
- **A per-request spend check in the API.** The cost happens in the worker, so the worker checks it. Jobs wait rather than fail, so nothing is lost.
- **Comparing eval result files byte for byte in CI.** Float noise across machines, run timestamps and git SHAs would fail it constantly. Floors about a point under the committed numbers catch real regressions.

## Consequences
- **Two shapes for one need.** Requester pages use `/portal`, PM pages the full routes. Both are typed from the same OpenAPI.
- **Behind a proxy**, per-client limits need `--forwarded-allow-ips`. Otherwise everyone shares the proxy's bucket.
- **What remains**, ranked with estimates, is in the README under "Production path". Auth, tenancy and Postgres come first.
