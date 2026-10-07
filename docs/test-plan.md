# Test plan

What we prove and how. Flows and formulas are in [spec.md](spec.md). Every flow in the spec maps to at least one item below. Module names are the planned ones; [requirements.md](requirements.md) points at them.

## 1. Pyramid

| Layer | Tool | Runs in | Scope | Planned location |
|---|---|---|---|---|
| Unit | pytest, offline | `make check`, CI | Deterministic logic: formulas, policy, verifiers, worker state machine, gateway bookkeeping with FakeLLM | `backend/tests/unit/` |
| API | pytest + FastAPI TestClient, temporary SQLite, FakeLLM | `make check`, CI | Endpoints, status transitions, idempotency, "nothing is deleted" | `backend/tests/api/` |
| Contract | `make openapi`, then `git diff --exit-code` on the schema and the generated TS types | CI | Frontend and backend agree on the API | `backend/openapi.json`, `frontend/src/api/` |
| Eval | `evals/` runner on the same pipeline and gateway | `make eval-offline` (free, CI); `make eval` (paid, manual, asks first) | Model and baseline quality, cost, latency | `evals/`, `evals/REPORT.md` |
| E2E | Playwright (Chromium), offline mode, seeded data | `make e2e`, CI | Golden paths GP1-GP6 | `e2e/` |
| Hooks | unittest | `make check-hooks` (with `HOOK_TESTS_REQUIRE_RUFF=1` and backend/.venv/bin on PATH, once the backend exists) | Prompt logging, guard, formatter | `.claude/hooks/test_hooks.py` |

No test calls a real model (CLAUDE.md rule 8). Unit and API tests inject FakeLLM, which returns scripted outputs, refusals, `max_tokens` stops, validation failures and provider errors.

## 2. What is test-first, and why

**Test-first** (the `tdd` skill: show the test failing, then make it pass). These are deterministic functions specified by formulas in the spec. A bug in any of them corrupts every number the PM sees, and a test written first is the executable form of the spec.

| Unit | Planned module |
|---|---|
| Redaction of emails and phone numbers | `unit/test_redaction.py` |
| Retrieval aggregation: per need by best match, top 5, canonical vector included | `unit/test_retrieval.py` |
| Routing score, bands, claim confirmed vs disputed, baseline through the same policy | `unit/test_routing.py` |
| Audit sampling by `sha256(request_id) mod 10` | `unit/test_audit_sampling.py` |
| Enrichment: account join; a missing account is scored without revenue and flagged | `unit/test_enrich.py` |
| Demand, urgency, strategic renormalization, priority | `unit/test_scoring.py` |
| Quote and number verifier (adjudication, strategic fit, brief, agent findings) | `unit/test_verify.py` |
| Worker: claim, backoff, stale reclaim, needs_review after N, terminal failures go straight to needs_review, an active claim becomes disputed, one-transaction results | `unit/test_worker.py` |
| Gateway: one ai_run per call with every field; redaction of every input; refusal is terminal; max_tokens and validation errors retried once, then terminal | `unit/test_gateway.py` |
| Overlap agent (should): step cap enforced; only read-only tools exposed; findings verified | `unit/test_agent.py` |
| Metric computations M1-M4, acceptance rate, Wilson interval | `unit/test_metrics.py` |
| Eval metric functions: precision, coverage, recall@5 | `unit/test_eval_metrics.py` |
| Frozen test split: hash unchanged | `unit/test_eval_freeze.py` |
| Seed data: every request labelled, clusters of two or more, references exist, the Excel split on both sides, the loader loads raw data only (passing) | `unit/test_seed_data.py` |
| SQLite in WAL mode with foreign keys (passing) | `unit/test_db.py` |

**API modules** (written alongside the endpoints, from the transitions in spec §5):

| Scope | Planned module |
|---|---|
| Submit: saved before any model call, saved when the provider fails, claim plus support in one transaction | `api/test_requests_api.py` |
| List, search, suggest (never calls the gateway); merged needs excluded | `api/test_needs_api.py` |
| Support: idempotent per requester | `api/test_support_api.py` |
| Inbox actions: accept, reject, undo, manual link, audit verdict, merge; every transition in spec §5; nothing deleted | `api/test_triage_api.py` |
| Metrics endpoint | `api/test_metrics_api.py` |
| Briefs and stakeholder updates (should): nothing goes out without approval | `api/test_briefs_api.py`, `api/test_updates_api.py` |

**Eval-first.** Every prompt (extraction, adjudication, strategic fit, brief, agent) gets its labelled cases before the prompt exists. A prompt or model change bumps the prompt version and requires an eval run (rule 7).

**Not test-first.** UI components and wiring, which are covered by e2e after the fact.

## 3. Eval plan

**Order:**
1. Write the hard cases by hand first: the Excel export example (finance vs IT admin) and the scheduled report family (email report, weekly PDF, Slack digest), each with variations. Then expand to about 8 families.
2. Write a label guide in `evals/README.md` before labelling:
   - same_need: the same problem for the same persona or job, whatever the solution.
   - related: an overlapping area, but a different problem or persona.
   - different: no overlap.
3. Split and **freeze the test set before any prompt exists.** `evals/datasets/test.jsonl` has its SHA-256 in `test.sha256`, and `test_eval_freeze.py` fails if it changes. Changing it requires a separate commit that gives a reason.

**Dataset:** about **150 labelled pairs**. Each pair is a new request plus the backlog state, with the gold need or NEW, plus gold persona and product area.

| Slice | Share | Purpose |
|---|---|---|
| Hard: same solution, different need | 30 (15 dev / 15 test) | Catches false merges; the thesis lives here |
| Hard: different solution, same need | 30 (15 / 15) | Paraphrase recall (retrieval and adjudication) |
| Clear duplicates | 44 (22 / 22) | Coverage of auto-linking |
| Genuinely new | 46 (23 / 23) | New-need accuracy, no forced links |

**Split:** dev 75 and test 75, stratified by slice.
- Thresholds, weights, s_min/s_max and prompts are tuned on dev only.
- The test split is run only to report results. It is never used for tuning.
- The test split is hand-written or hand-reviewed. LLM-generated paraphrases are allowed only in dev, and each one is reviewed.

**Metrics, per configuration (C0-C3, and C4 if built):**

| Metric | Definition |
|---|---|
| Retrieval recall@5 | The gold need is among the top 5 candidates. Reported overall and on the paraphrase slice; the gate is ≥ 90% (ADR 0002). |
| Auto-link precision | Share of auto-links that are correct. This is the offline estimate of the false-merge rate; in production, M4 is measured on the audit sample. |
| Auto-link coverage | Share of true duplicates that get auto-linked. |
| Gray-zone share | Share of requests sent to the inbox, which is PM work. |
| New-need accuracy | True new requests not linked to anything. |
| Hard-slice accuracy | Accuracy on each hard slice separately. |
| Extraction | Exact accuracy on persona and product area. |
| Cost and latency | Cost per request; p50 and p95 latency per step, from ai_runs. |
| Calibration (only to decide C4) | On dev, the precision of Haiku's auto-band decisions (routing score ≥ T_auto) compared with C3's (ADR 0006). |

**Baseline:** C0 runs through the same routing code, with the label replaced by `similarity ≥ s_dup` and extraction done by heuristics. It runs free on every CI build (`make eval-offline`). An LLM step earns its cost only if it beats C0 on the hard slices.

**Choosing thresholds (on dev):**
- **T_auto:** the lowest value that gives auto-link precision ≥ 97% with at least 10 auto-links.
- **T_suggest:** the highest value at which ≥ 95% of the true duplicates that weren't auto-linked still score at or above it, so they land in the gray zone instead of becoming new needs.
- Both are then confirmed once on test, and reported with Wilson 95% intervals. Starting values in config are 0.90 and 0.60 (spec section 8).

**Sample size and error bars:**
- With 75 test cases, intervals are wide: 70/75 correct gives [85%, 97%]. The test split can only detect large differences.
- If two configurations' intervals overlap on the deciding metrics, the simpler and cheaper one wins (ADR 0006).
- The report states that the data is synthetic (assumption A1). The production audit sample (M4) is what narrows the false-merge bound over time.

**Cost of live runs:**
- A full run of C1-C3 over 150 cases is about 900 calls and about $8 at the spec's token assumptions.
- A run on dev only is about half of that.
- `make eval` prints the call count and expected cost and asks first. Results and deltas go in `evals/REPORT.md`.

**Should-flow slices** (added when the flow is built):
- Strategic fit: a small rubric set; checks that each quote is verified.
- Brief: cases with planted fabricated quotes and numbers; the verifier must flag all of them.
- Agent: cases with known overlaps and dependencies; precision of its findings and step-cap compliance.
- Commitment flags (F7): drafts containing promised dates or features the PM didn't make.

## 4. E2E golden paths (offline, seeded, Chromium)

| ID | Path | Proves |
|---|---|---|
| GP1 | The requester types; matching needs appear (problem plus persona); "this is my need" plus why and severity; the support shows as claimed and not counted; once the worker confirms it, it counts on the need page | F0, F1, F3 (claims) |
| GP2 | A new request is auto-linked; the PM finds it in the read-only Auto-linked tab, with its label, score and rationale; the PM undoes it; an unlink LinkEvent is recorded (nothing deleted) and the request is back in Suggestions | F2, F3, F5 |
| GP3 | A gray-zone request shows in the inbox side by side; the PM accepts; demand and the score breakdown on the need update | F0, F4, F5 |
| GP4 | The provider fails (a test-only switch, active only when `APP_ENV=test`); the request is in Needs review with the reason; the PM links it by hand | F2 failure path, rule 2 |
| GP5 | A sampled auto-link appears in the Audit tab; the PM marks it false_merge; the link is undone, the request is back in Suggestions, and M4 in the metrics view updates | F3 audit, F8, M4 |
| GP6 | The metrics view shows M1, M2, M4, the acceptance rate and the ai_runs cost and latency summary | F8 |

Seed scenarios are designed so that the offline provider deterministically puts one request in each band.

## 5. What we deliberately don't test

| Not tested | Why |
|---|---|
| Real provider calls in CI | Cost and flakiness. Covered by `make eval`, run manually and recorded. |
| The wording of model output | Evals measure quality; asserting on fake output proves nothing (testing rule). |
| fastembed internals | A fake Embedder is used in unit tests; one slow smoke test checks the real model ranks a paraphrase above an unrelated text. |
| Load, concurrency beyond one process, typing latency as a CI gate | One process by design (ADR 0005). The typing latency is measured locally and reported, not gated. |
| Auth, email and Slack delivery, multiple languages, browsers other than Chromium | Non-goals (spec section 12). |
| Should flows and the cascade before they are built | Their tests and eval slices are added together with the code. |
