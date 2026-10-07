# Test plan

What we prove and how. Flows and formulas are in [spec.md](spec.md). Every flow in the spec maps to at least one item below, or is marked not built. Module names are the ones in the repo; [requirements.md](requirements.md) points at them.

## 1. Pyramid

| Layer | Tool | Runs in | Scope | Location |
|---|---|---|---|---|
| Unit | pytest, offline | `make check`, CI | Deterministic logic: formulas, policy, verifiers, worker state machine, gateway bookkeeping with FakeLLM | `backend/tests/unit/` |
| API | pytest + FastAPI TestClient, temporary SQLite, FakeLLM | `make check`, CI | Endpoints, status transitions, idempotency, "nothing is deleted" | `backend/tests/api/` |
| Contract | `make openapi` then `git diff --exit-code backend/openapi.json`; `npm run gen:api` then `git diff --exit-code` on the generated types | CI (backend and frontend jobs) | Frontend and backend agree on the API | `backend/openapi.json`, `frontend/src/api/schema.d.ts` |
| Eval | `evals/` runner on the same pipeline and gateway | `make eval-offline` (free, CI); `make eval` (paid, manual, asks first) | Model and baseline quality, cost, latency | `evals/`, `evals/REPORT.md` |
| E2E | Playwright (Chromium), offline mode, seeded data | `make e2e`, CI | Golden paths GP1-GP7 | `frontend/e2e/` |
| Hardening | Rate limits, body caps, CORS and headers, request IDs into ai_runs, health and readiness, log redaction, portal data boundary, spend ceiling | `make test`, CI | ADR 0011 | `api/test_hardening_api.py`, `api/test_portal_api.py` |
| Eval gate | The free offline baseline must stay above `evals/gates.yaml` | `make eval-gate`, CI | REPORT §1 | `evals/gate.py`, `evals/tests/test_gate.py` |
| Hooks | unittest | `make check-hooks` (with `HOOK_TESTS_REQUIRE_RUFF=1` and backend/.venv/bin on PATH, once the backend exists) | Prompt logging, guard, formatter | `.claude/hooks/test_hooks.py` |

No test calls a real model (CLAUDE.md rule 8). Unit and API tests inject FakeLLM, which returns scripted outputs, refusals, `max_tokens` stops, validation failures and provider errors.

## 2. What is test-first, and why

**Test-first** (the `tdd` skill: show the test failing, then make it pass). These are deterministic functions specified by formulas in the spec. A bug in any of them corrupts every number the PM sees, and a test written first is the executable form of the spec.

| Unit | Module |
|---|---|
| Redaction of emails and phones, not other numbers (passing) | `unit/test_redaction.py` |
| Retrieval: best match per need, canonical vector, top k (passing) | `unit/test_retrieval.py` |
| Routing score, bands, seeded 10% audit sample (`sha256(seed:id) mod 10000 < rate × 10000`), claim verdict, baseline through the same policy (passing) | `unit/test_policy.py` |
| Baseline bands and threshold loading (passing) | `unit/test_baseline.py` |
| Demand, urgency, strategic fit, priority, quadrant, owner, re-rating crossings, ties, config validation; a missing account or ARR scores zero revenue and is flagged (passing) | `unit/test_scoring.py` |
| Quote verification: made-up quotes dropped in adjudication and strategic fit (passing) | `unit/test_pipeline.py`, `unit/test_strategic_fit.py` |
| Gateway: AIRun per call, refusal terminal, one repair retry, max_tokens retry, transient errors, redaction before the client, XML tags (passing) | `unit/test_gateway.py` |
| Live client bookkeeping with a stubbed SDK: validation, cost, refusal, max_tokens, error classes (passing) | `unit/test_anthropic_client.py` |
| Pipeline with FakeLLM: auto, gray zone, new need, audit flag, prompt injection, redaction, idempotency, claims (passing) | `unit/test_pipeline.py` |
| Worker: one at a time, attempts and last error, backoff, 3 failures to needs_review, refusal, stale reclaim, outage never fails a submission (passing) | `unit/test_worker.py` |
| Strategic fit with FakeLLM: what is sent (no requester fields, redacted, escaped), per-goal rows, quote check, coverage repair, worker retries and failure, merged and stale needs (passing) | `unit/test_strategic_fit.py` |
| Commitment check: dates, timing and promises flagged unless the PM set a date (passing) | `unit/test_commitments.py` |
| Test-only fault switch (passing) | `unit/test_fault_injection.py` |
| Embedders: fake determinism, real model offline (passing) | `unit/test_embeddings.py` |
| Seed data: every request labelled, clusters of two or more, references exist, the Excel split on both sides, recorded fit ratings (passing) | `unit/test_seed_data.py` |
| SQLite in WAL mode with foreign keys (passing) | `unit/test_db.py` |
| Metric computations M1-M4, acceptance rate, Wilson interval (passing) | `api/test_workspace_api.py`, `api/test_updates_api.py` (M3) |
| Priority on read: breakdown per need, confirmed support only, each account once, quadrant view, a config-only weight change re-ranks (passing) | `api/test_priority_api.py` |
| Frozen test split: hash, uncommitted changes, same-commit rule (passing) | `evals/tests/test_dataset.py` |
| Eval metrics with hand-computed values (passing) | `evals/tests/test_metrics.py` |
| Threshold choice on dev (passing) | `evals/tests/test_tune.py` |
| Runner logic: dev labels, noise, raw tuning mode, each test case counted once (passing) | `evals/tests/test_run.py` |
| Strategic-fit eval and the offline gate (passing) | `evals/tests/test_fit.py`, `evals/tests/test_gate.py` |
| Requester progress: stuck after 2 minutes (passing) | `frontend/src/pages/requester/progress.test.ts` (Vitest) |
| Decision brief with FakeLLM scripted to call tools: the agent stops at 8 tool calls and flags the result incomplete; only three strict read-only tools, anything else rejected unrun; bad arguments are an error result; findings cite a request of the related need with a verbatim quote (fabricated, wrong-need, self and merged findings flagged); tool results redacted; trajectory with arguments, result size, latency and turn run; the brief survives an agent failure or timeout and says so; money only from the data (invented figures removed); unknown fact keys flagged; one repair round, then flags; related needs must be verified findings; review fixes: a raising tool is an error step, accented text reaches the model unescaped, one max_tokens retry per agent turn, a failed repair call keeps the first brief, the version with fewer failing claims wins, at most 25 requests ranked by severity, overlapping figures replaced once, the 5% tolerance boundary, invented figures removed from failing quotes; offline baseline and template; the markdown example (passing) | `unit/test_brief.py` |
| Live client agent turns: strict tools, `tool_choice` none for the last turn, validated answer, refusals and limits; a cached step marks its system prompt; a long step gets its own timeout; cache tokens recorded and costed (passing) | `unit/test_anthropic_client.py`, `unit/test_gateway.py` |

**API modules** (written alongside the endpoints, from the transitions in spec §5):

| Scope | Module |
|---|---|
| Submit: saved before any model call, validation and on-behalf rules (passing) | `api/test_requests_api.py` |
| Saved when the provider fails: an outage never fails a submission (passing) | `unit/test_worker.py::test_a_provider_outage_never_fails_the_submission`, e2e GP6 |
| List, search, filters, sorts, detail; merged needs excluded (passing) | `api/test_needs_api.py` |
| Support: a claim first, idempotent per requester, concurrent first supports, merged needs 409 (passing) | `api/test_support_api.py` |
| Inbox actions: accept, reject, undo, audit verdict; LinkEvents record who; nothing deleted; an emptied need sends pending suggestions nowhere (passing; manual link and merge not built) | `api/test_triage_api.py` |
| The door: similar needs from embeddings only, merged needs excluded, never calls the gateway (passing) | `api/test_similar_api.py` |
| Error shape: 422, 404, 405, 500 (passing) | `api/test_errors_api.py` |
| Requesters list (passing) | `api/test_requesters_api.py` |
| Metrics endpoint and the PM workspace (passing) | `api/test_workspace_api.py` (`GET /metrics`) |
| Stakeholder updates: nothing goes out without approval, compare-and-set, superseded drafts (passing) | `api/test_updates_api.py` |
| Requester portal: no PM data (passing) | `api/test_portal_api.py` |
| Briefs: 202 and the worker builds it, newest returned, a waiting brief reused (and a partial unique index behind it), 404/409/422, failed with the reason, transient retry, reclaim after a crash, every call listed by trace ID even for a failed brief, the last ready brief kept reachable (passing) | `api/test_briefs_api.py` |

**Eval-first.** Adjudication was eval-first: the 17 hard cases and the frozen test set came before any prompt (§3). Extraction is evaluated only through routing (row "Extraction" below). Two exceptions are recorded in [ai-development.md](ai-development.md#test-first-and-eval-first): `strategic_fit_v1` and its cases landed in the same commit, and `stakeholder_update_v1` has no eval. A prompt or model change bumps the prompt version and requires an eval run (rule 7).

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
| Extraction | Not built as its own metric: extraction is evaluated only end to end, through the routing decision it feeds (REPORT §3 shares one Haiku extraction across strategies). |
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
- Brief and agent: not built as eval slices yet. The verifier is covered deterministically by `unit/test_brief.py` (planted fabricated quotes, figures, fact keys and related needs); the quality of `related_needs_v1` and `decision_brief_v1` has no eval (ADR 0012). The comparison to beat is the offline baseline.
- Commitment flags (F7): covered by the deterministic check's unit tests (`unit/test_commitments.py`), not by an eval. `stakeholder_update_v1` itself has no eval (requirements D8).

## 4. E2E golden paths (offline, seeded, Chromium)

GP1-GP4 and GP7 (#24) were written before the pages as the contract for them; GP5 (#19) and GP6 (#21) were written after the code they test ([ai-development.md](ai-development.md#test-first-and-eval-first)). All of them select by accessible names, roles and visible text, not CSS. `make e2e` starts a fresh offline API on :8001 (its own `backend/data/e2e.db`, reseeded from the recorded snapshot every run) with the in-process worker, and the web app on :5174; the specs share that database and run one at a time.

| ID | Spec | Path | Proves |
|---|---|---|---|
| GP1 | `e2e/discover-and-support.spec.ts` | Kai types "Can we log in with Okta?"; the SSO need is the closest match, phrased as a problem for a persona; "This is my need", why it matters and Blocker; no duplicate request is filed; the need page lists the support with its severity and whether it counts yet | F0, F1, F3 (claims); R8, R9 |
| GP2 | `e2e/submit-and-track.spec.ts` | Lily submits "Book meeting rooms" (offline similarity 0.61, below the suggest band); My requests shows it, updates to Processed without a reload, and links to the new need, which shows it was created by the offline baseline | F2; R7 |
| GP3 | `e2e/pm-triage.spec.ts` | A gray-zone request (similarity 0.735 to SSO, between 0.651 and 0.767) is a suggestion side by side with SSO, with source and why; the PM accepts; marks one audit-sample auto-link correct; undoes an auto-link after a confirmation, and it leaves the Auto-linked tab | F3, F5; Q6 |
| GP4 | `e2e/pm-priorities.spec.ts` | The quadrant shows clear wins, strategic bets, popular but off-strategy, park and not rated yet, with every undecided need placed; the SSO row's "Explain score" opens a breakdown whose demand, urgency and strategic-fit sections explain their inputs and whose points add up to the score in the table | F4, §8; R10 |
| GP5 | `e2e/stakeholder-updates.spec.ts` | The PM marks SSO planned with a reason that says "next quarter" and no date; personal drafts appear (offline template), none sent; Priya's refers to what she asked for and is flagged; the PM fixes and approves every personal draft; AI Ops shows M3 with a value; Priya sees the update on the need page | F7, M3; ADR 0010 |
| GP6 | `e2e/provider-failure.spec.ts` | The provider fails (a fault switch that exists only with `APP_ENV=test`, triggered by a marker in the text): the request is saved, the requester sees "Needs review" with a plain reason, the PM sees it in Needs review with the real reason. Linking it by hand isn't built yet | F2 failure path, rule 2 |
| GP7 | `e2e/brief-me.spec.ts` | The PM opens the SSO need and clicks "Brief me"; the brief appears (offline baseline and template) with its source, summary, recommendation, impact claims showing their cited values, verbatim evidence and "All N claims checked"; "How this brief was built" shows the agent steps against the cap of 8 and the model calls | F6; ADR 0012 |

The offline texts were chosen by measuring the real embedder against the seeded backlog, so each lands in its band deterministically; a seed or threshold change can move them, and the spec comments give the measured similarity.

Notes for building the pages against these specs:
- **Shared database, fixed order.** Specs run one at a time in file order (brief-me, discover-and-support, pm-priorities, pm-triage, provider-failure, stakeholder-updates, submit-and-track). The triage spec changes the backlog (an accept, an undo that creates a need); the others don't depend on its result. Offline, any membership change queues a strategic-fit rating that only live mode runs, so touched needs show "Pending".
- **Offline claims are disputed.** GP1's reason is 0.584 similar to SSO, below the suggest band, so the baseline disputes the claim; the spec accepts any of the three states.
- **Polling.** My requests and the triage inbox must refetch on an interval while anything is pending (headless browsers don't refocus), or the 30 s waits fail.
- **Stable hooks the pages must provide:** `data-testid` `support-confirmation`, `request-status`, `need-link`, `need-source`, `routing-badge`, `priority`, `points` (one per rated component; none for an unrated one), `priority-total`; `data-request-id` on Auto-linked articles; toasts through sonner's "Notifications" region.
- **API work the pages needed** is built (2026-10-07): AI source and routing parts on triage items, a written reason for baseline decisions, `GET /requests?requester_id=`, the Auto-linked list (newest 50, with a total), need origin, analysis, evidence, updates and audit trail, `PATCH /needs/{id}/status`, `GET /metrics`, and the requester views under `/portal`. All seven specs pass (`make e2e`, and in CI); contract tests in `api/test_workspace_api.py`, `api/test_updates_api.py` and `api/test_portal_api.py`.

## 5. What we deliberately don't test

| Not tested | Why |
|---|---|
| Real provider calls in CI | Cost and flakiness. Covered by `make eval`, run manually and recorded. |
| The wording of model output | Evals measure quality; asserting on fake output proves nothing (testing rule). |
| fastembed internals | A fake Embedder is used in unit tests; one slow smoke test checks the real model ranks a paraphrase above an unrelated text. |
| Load, concurrency beyond one process, typing latency as a CI gate | One process by design (ADR 0005). The typing latency is measured locally and reported, not gated. |
| Auth, email and Slack delivery, multiple languages, browsers other than Chromium | Non-goals (spec section 12). |
| Should flows and the cascade before they are built | Their tests and eval slices are added together with the code. |
