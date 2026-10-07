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
| Demand, urgency, strategic fit, priority, quadrant, owner, re-rating crossings, ties, config validation (passing) | `unit/test_scoring.py` |
| Quote and number verifier (adjudication, strategic fit, brief, agent findings) | `unit/test_verify.py` |
| Worker: claim, backoff, stale reclaim, needs_review after N, terminal failures go straight to needs_review, an active claim becomes disputed, one-transaction results | `unit/test_worker.py` |
| Gateway: one ai_run per call with every field; redaction of every input; refusal is terminal; max_tokens and validation errors retried once, then terminal | `unit/test_gateway.py` |
| Overlap agent (should): step cap enforced; only read-only tools exposed; findings verified | `unit/test_agent.py` |
| Metric computations M1-M4, acceptance rate, Wilson interval | `unit/test_metrics.py` |
| Frozen test split: hash, uncommitted changes, same-commit rule (passing) | `evals/tests/test_dataset.py` |
| Eval metrics with hand-computed values (passing) | `evals/tests/test_metrics.py` |
| Threshold choice on dev (passing) | `evals/tests/test_tune.py` |
| Retrieval: best match per need, canonical vector, top k (passing) | `unit/test_retrieval.py` |
| Baseline bands and threshold loading (passing) | `unit/test_baseline.py` |
| Embedders: fake determinism, real model offline (passing) | `unit/test_embeddings.py` |
| Runner logic: dev labels, noise, raw tuning mode, each test case counted once (passing) | `evals/tests/test_run.py` |
| Routing score, bands, seeded 10% audit sample, claim verdict (passing) | `unit/test_policy.py` |
| Redaction of emails and phones, not other numbers (passing) | `unit/test_redaction.py` |
| Gateway: AIRun per call, refusal terminal, one repair retry, max_tokens retry, transient errors, redaction before the client, XML tags (passing) | `unit/test_gateway.py` |
| Pipeline with FakeLLM: auto, gray zone, new need, audit flag, prompt injection, redaction, idempotency, claims (passing) | `unit/test_pipeline.py` |
| Worker: one at a time, attempts and last error, backoff, 3 failures to needs_review, refusal, stale reclaim, outage never fails a submission (passing) | `unit/test_worker.py` |
| Priority on read: breakdown per need, confirmed support only, each account once, quadrant view, a config-only weight change re-ranks (passing) | `api/test_priority_api.py` |
| Strategic fit with FakeLLM: what is sent (no requester fields, redacted, escaped), per-goal rows, quote check, coverage repair, worker retries and failure, merged and stale needs, `fit_texts` (passing) | `unit/test_strategic_fit.py` |
| Seed data: every request labelled, clusters of two or more, references exist, the Excel split on both sides, the loader loads raw data only (passing) | `unit/test_seed_data.py` |
| SQLite in WAL mode with foreign keys (passing) | `unit/test_db.py` |

**API modules** (written alongside the endpoints, from the transitions in spec §5):

| Scope | Planned module |
|---|---|
| Submit: saved before any model call, saved when the provider fails, claim plus support in one transaction | `api/test_requests_api.py` |
| List, search, suggest (never calls the gateway); merged needs excluded | `api/test_needs_api.py` |
| Support: idempotent per requester | `api/test_support_api.py` |
| Inbox actions: accept, reject, undo, audit verdict; LinkEvents record who; nothing deleted (passing; manual link and merge not built yet) | `api/test_triage_api.py` |
| The door: similar needs from embeddings only, merged needs excluded (passing) | `api/test_similar_api.py` |
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
3. **Freeze the test set before any prompt or threshold exists** (done in commit `3ce8b0d`). `evals/datasets/FROZEN` holds the SHA-256 of `test.jsonl`. The runner refuses to run if the hash differs, if either file has uncommitted changes, or if the last commit that touched `test.jsonl` didn't also touch `FROZEN` (`evals/dataset.py`, tested in `evals/tests/test_dataset.py`).

**Splits** (as built; evals/REPORT.md §1):

| Split | What | Size |
|---|---|---|
| dev | The seed stream (`backend/seed/`) replayed in arrival order. Each request is routed against the backlog so far; right = the right existing need, or "new" when its cluster first appears. The backlog then takes the true label, so errors don't compound. All tuning happens here. | 62 decisions (44 repeats, 18 first appearances) |
| test | `evals/datasets/test.jsonl`: one request per case, routed against the full seeded backlog (17 needs, their requests, one canonical text per need). Run only to report results; never used for tuning. | 150 cases |

Test-set composition. Robert's 17 handwritten cases (`H…`, `reviewed_by_human: true`) are the pattern; Claude generated the other 133 (`T…`, `reviewed_by_human: false`). The handwritten cases are reported as their own slice.

| Slice | Cases | Purpose |
|---|---|---|
| Same solution, different need | 25 | Catches false merges; the thesis lives here |
| Different solution, same need | 25 | Recall across different solutions |
| Hard negative | 25 | Related but different needs |
| Paraphrase | 25 | Same need, different words (the retrieval gate) |
| Clear duplicate | 20 | Coverage of auto-linking |
| New need | 24 | "New" accuracy, no forced links |
| Prompt injection | 2 | The injected text must change nothing |
| Spanish | 4 | Non-English input |

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

**Baseline (C0):** routes on the top retrieval similarity alone (`backend/app/ai/baseline.py`), with no extraction and no label, using the same three bands. It is also the app's offline mode. It runs free with `make eval-offline`. An LLM step earns its cost only if it beats C0 on the hard slices and on "new".

**Choosing thresholds (on dev, `make eval-tune`, written to `config/routing.yaml`):**
- **T_auto:** the lowest value that gives auto-link precision ≥ 97% with at least 10 auto-links. If none does, the baseline never auto-links.
- **T_suggest:** the highest value at which ≥ 95% of the true duplicates that weren't auto-linked still score at or above it, so they land in the gray zone instead of becoming new needs.
- Both are confirmed once on test and reported with Wilson 95% intervals. Thresholds are stored unrounded. The baseline's thresholds (0.7666 and 0.6508) didn't transfer: auto false merges were 0/13 on dev but 6/59 on test, all in hard slices that dev lacks (REPORT §1, finding 1). Dev needs hard cases. The test split has been seen, so any later baseline re-tune is labelled post hoc.

**Sample size and error bars:**
- With 150 test cases, intervals are still wide (70/75 on a slice gives [85%, 97%]); per-slice numbers (n = 20-25) can only show large differences.
- If two configurations' intervals overlap on the deciding metrics, the simpler and cheaper one wins (ADR 0006).
- The report states that the data is synthetic (assumption A1). The production audit sample (M4) is what narrows the false-merge bound over time.

**Cost of live runs:**
- A full run of C1-C3 over 150 cases is about 900 calls and about $8 at the spec's token assumptions.
- A run on dev only is about half of that.
- `make eval` prints the call count and expected cost and asks first. Results and deltas go in `evals/REPORT.md`.

**Should-flow slices** (added when the flow is built):
- Strategic fit: 10 seeded needs plus one prompt-injection case, rated 0-3 per goal by Robert before any paid call (`evals/datasets/strategic_fit.jsonl`; `evals/fit.py` refuses a paid run until every case is labelled and reviewed). Reports agreement within one point, exact agreement, MAE and Spearman of S against constant and embedding baselines, plus the quote verification rate (REPORT §5). Report-only: no dev split.
- Brief: cases with planted fabricated quotes and numbers; the verifier must flag all of them.
- Agent: cases with known overlaps and dependencies; precision of its findings and step-cap compliance.
- Commitment flags (F7): drafts containing promised dates or features the PM didn't make.

## 4. E2E golden paths (offline, seeded, Chromium)

Written before the pages (2026-10-07) as the contract for them: accessible names, roles and visible text, not CSS. `make e2e` starts a fresh offline API on :8001 (its own `backend/data/e2e.db`, reseeded from the recorded snapshot every run) with the in-process worker, and the web app on :5174; the specs share that database and run one at a time.

| ID | Spec | Path | Proves |
|---|---|---|---|
| GP1 | `e2e/discover-and-support.spec.ts` | Kai types "Can we log in with Okta?"; the SSO need is the closest match, phrased as a problem for a persona; "This is my need", why it matters and Blocker; no duplicate request is filed; the need page lists the support with its severity and whether it counts yet | F0, F1, F3 (claims); R8, R9 |
| GP2 | `e2e/submit-and-track.spec.ts` | Lily submits "Book meeting rooms" (offline similarity 0.61, below the suggest band); My requests shows it, updates to Processed without a reload, and links to the new need, which shows it was created by the offline baseline | F2; R7 |
| GP3 | `e2e/pm-triage.spec.ts` | A gray-zone request (similarity 0.735 to SSO, between 0.651 and 0.767) is a suggestion side by side with SSO, with source and why; the PM accepts; marks one audit-sample auto-link correct; undoes an auto-link after a confirmation, and it leaves the Auto-linked tab | F3, F5; Q6 |
| GP4 | `e2e/pm-priorities.spec.ts` | The quadrant shows clear wins, strategic bets, popular but off-strategy, park and not rated yet, with every undecided need placed; the SSO row's "Explain score" opens a breakdown whose demand, urgency and strategic-fit sections explain their inputs and whose points add up to the score in the table | F4, §8; R10 |
| planned | provider failure | The provider fails (a test-only switch, active only when `APP_ENV=test`); the request is in Needs review with the reason; the PM links it by hand | F2 failure path, rule 2 |
| planned | metrics | The metrics view shows M1, M2, M4, the acceptance rate and the ai_runs cost and latency summary | F8 |

The offline texts were chosen by measuring the real embedder against the seeded backlog, so each lands in its band deterministically; a seed or threshold change can move them, and the spec comments give the measured similarity.

Notes for building the pages against these specs:
- **Shared database, fixed order.** Specs run one at a time in file order (discover, priorities, triage, submit). The triage spec changes the backlog (an accept, an undo that creates a need); the others don't depend on its result. Offline, any membership change queues a strategic-fit rating that only live mode runs, so touched needs show "Pending".
- **Offline claims are disputed.** GP1's reason is 0.584 similar to SSO, below the suggest band, so the baseline disputes the claim; the spec accepts any of the three states.
- **Polling.** My requests and the triage inbox must refetch on an interval while anything is pending (headless browsers don't refocus), or the 30 s waits fail.
- **Stable hooks the pages must provide:** `data-testid` `support-confirmation`, `request-status`, `need-link`, `need-source`, `routing-badge`, `priority`, `points` (one per rated component; none for an unrated one), `priority-total`; `data-request-id` on Auto-linked articles; toasts through sonner's "Notifications" region.
- **API work the pages need** (not built yet): the request's AI source on triage items and needs (model or offline-baseline); a deterministic rationale for baseline decisions (e.g. "Embedding similarity 0.735 to need 1; suggest band 0.651-0.767"), so "why" is never empty; `GET /requests?requester_id=` for My requests; an Auto-linked list for the triage tab; and a PM identity for the `by` field of triage actions.

## 5. What we deliberately don't test

| Not tested | Why |
|---|---|
| Real provider calls in CI | Cost and flakiness. Covered by `make eval`, run manually and recorded. |
| The wording of model output | Evals measure quality; asserting on fake output proves nothing (testing rule). |
| fastembed internals | A fake Embedder is used in unit tests; one slow smoke test checks the real model ranks a paraphrase above an unrelated text. |
| Load, concurrency beyond one process, typing latency as a CI gate | One process by design (ADR 0005). The typing latency is measured locally and reported, not gated. |
| Auth, email and Slack delivery, multiple languages, browsers other than Chromium | Non-goals (spec section 12). |
| Should flows and the cascade before they are built | Their tests and eval slices are added together with the code. |
