# Distill: product spec

Source of requirements: [assignment.md](assignment.md). Traceability: [requirements.md](requirements.md). Design: [architecture.md](architecture.md), [adr/](adr/). Tests and evals: [test-plan.md](test-plan.md).

## 1. Problem and thesis

Brightboard is a fictional B2B dashboards and analytics SaaS with enterprise, mid-market and SMB customers, plus prospects. Feature requests come from customers, prospects, support, sales and internal teams. Almost every pain in the brief starts at intake:
- Duplicates enter there.
- Demand gets split across five phrasings of the same need.
- PMs spend their hours there.
- Nobody can tell a customer anything until requests are organized.

**Thesis.** Requests describe solutions; the unit of value is the underlying need, meaning a problem for a persona.
- "Excel export" from a finance lead and "Excel export" from an IT admin are two different needs.
- "Scheduled email report", "weekly PDF" and "Slack KPI digest" are one need.

Distill turns every request, as it arrives, into a deduplicated, need-centric, evidence-weighted signal. The PM handles exceptions instead of reading the stream. Prioritization, briefs and stakeholder updates are thin layers on top once that holds.

## 2. Users and who benefits

| User | Today | With Distill |
|---|---|---|
| PM (triage owner) | Reads every request, searches by keyword, merges by hand | Reviews only the gray zone, disputes, failures and a 10% audit sample |
| Requester (customer, CS, sales, internal) | Submits into a void; duplicates are invisible | Sees existing needs while typing; adding support takes one click and their "why" counts as evidence |
| CS and sales | Can't see which of their accounts want what | Sees the accounts and revenue behind each need, and renewals at risk |
| Product leader | Gets vote counts, or opinions | Gets demand, urgency and strategic fit shown separately, and (should) a verified decision brief |

## 3. Workflow before and after

| Step | Before | After (who does it) |
|---|---|---|
| Submit | Free text into a form or a board | The form suggests matching needs, phrased as problem plus persona, before the request is saved (code, no LLM) |
| Dedupe | The PM spots duplicates from memory | Retrieval finds candidates, the LLM judges same need or not, and code routes (AI and code) |
| Understand | The PM rereads the thread | The extraction stores problem, persona, job to be done, proposed solution, area and severity (AI) |
| Weigh | Vote count | Revenue, segment, renewals and severity, computed (code); strategic fit is rated (AI, should) |
| Decide | Spreadsheet triage | The PM inbox holds exceptions only; the PM decides status (human) |
| Communicate | Ad hoc, often never | Drafted updates the PM approves (AI and human, should) |

## 4. Flows

Must = the golden path and is built first. Should = built only after the golden path works end to end. "Proven by" names the test, eval or metric (details in [test-plan.md](test-plan.md)).

| ID | Flow | Level | Proven by |
|---|---|---|---|
| F0 | **Browse, search and support.** List and search needs. The need page shows member requests, supporters, the score breakdown, and every AI value with its source, confidence and rationale. Support records why it matters and a severity, and is idempotent per requester. | must | API tests (needs, support); e2e GP1 and GP3 |
| F1 | **Dedupe at the door (simple).** While the requester types, show the 5 closest needs, phrased as problem plus persona. This uses embeddings only and no LLM, under 300 ms server-side. "This is my need" saves the request with a **requester-claimed link** plus support. | must | API test (suggest never calls the gateway; ranking); e2e GP1; metric M2 (door deflection) |
| F2 | **Intake workflow** (background, after save): redact, embed, retrieve, extract, adjudicate, route, enrich, score (section 6). | must | Unit tests per deterministic step and for the worker; evals (extraction, retrieval recall@5, adjudication); e2e GP4 (failure path) |
| F3 | **Confidence policy.** Routing score (section 8) produces: auto-link (labelled, undoable, 10% audit sample), suggestion in the inbox, or new need. A requester-claimed link is confirmed or disputed. | must | Unit tests (routing, policy, audit sampling); threshold choice in evals/REPORT.md; metric M4; e2e GP2 and GP5 |
| F4 | **Prioritization.** Demand, urgency and score are computed in code (must). Strategic fit is rated by the model against config/goals.yaml, with the quote verified in code (should). Popular and strategic are shown separately. | must (computed) / should (fit) | Scoring unit tests; quote-verifier unit test; strategic-fit eval slice (should) |
| F5 | **PM triage inbox.** Action tabs: Suggestions, Disputed claims, Needs review (AI failed), Audit sample. A read-only Auto-linked tab lists every auto-link with an undo button and requires no action (CLAUDE.md rule 2). Both texts side by side, with accept, reject, undo, link manually, new need, or merge needs. | must | `api/test_triage_api.py` (each transition in §5; links never deleted); e2e GP2-GP5; metric: suggestion acceptance rate |
| F6 | **Decision brief.** A workflow: gather the facts, make one LLM call, verify every quote and number in code. An optional **overlap agent** finds needs this one overlaps with, blocks or depends on, using read-only search tools and a step cap; its findings feed the brief as cited evidence. If time runs short, the agent is dropped and the brief stays. | should | `unit/test_verify.py`; `unit/test_agent.py` (step cap, read-only tools) with FakeLLM; eval with fabricated quotes and numbers |
| F7 | **Close the loop.** When a need's status changes, the AI drafts a requester update and a CS note per account, and flags commitments the PM didn't make. The PM approves. Delivery is in-app only. | should | `api/test_updates_api.py` (nothing goes out without approval); commitment-flag eval slice; metric M3 |
| F8 | **Metrics and AI Ops view (minimal).** Metrics M1, M2 and M4 and the guardrails (M3 is added with F7), plus a summary of ai_runs: cost per request, p50/p95 latency per step, failure rate, by model and prompt version. | must | `unit/test_metrics.py`; `api/test_metrics_api.py`; e2e GP6 |

## 5. Data model

All tables live in SQLite. Nothing an AI produced is ever deleted: links change state, and every change is an event.

| Table | Key fields | Notes |
|---|---|---|
| account | id, name, segment (enterprise, mid_market, smb, prospect), arr, pipeline_value, renewal_date | The seeded "CRM". Enrichment reads it in code. |
| requester | id, name, role, account_id | No auth: the demo has a persona switcher (assumption A3). |
| need | id, title (problem plus persona), problem, persona, job_to_be_done, product_area, status (open, planned, in_progress, shipped, declined, merged), merged_into_id, created_by (ai, pm), source_extraction_id | Status is set only by a PM, except `merged` (below). An AI-created need shows its source extraction's confidence and rationale. Merged needs are excluded from list, search, suggestions and retrieval. |
| request | id, requester_id, title, description, why_it_matters, redacted_text, severity (blocker, workaround, nice_to_have), claimed_need_id, status (see below), needs_review_reason | Saved before any model call. redacted_text is computed at save (rule 9). |
| extraction | request_id, problem, persona, job_to_be_done, proposed_solution, product_area, severity_signals, evidence (a quote per field, verified in code), model_confidence, rationale, source (llm, offline_baseline, recorded), ai_run_id | Validated by Pydantic before it is persisted. For extracted fields, "confidence" means the model's stated confidence plus whether each evidence quote verified. |
| link | id, request_id, need_id, source (ai_auto, ai_suggested, ai_new_need, ai_related, requester_claimed, pm_manual), state (proposed, active, disputed, rejected, undone, related), routing_score, label, model_confidence, rationale, quotes, audit_sampled, audit_verdict (correct, false_merge), decided_by, decided_at | Never deleted. Only active links count as demand. Only proposed and disputed links appear in the action tabs. `related` links are informational. |
| support | need_id, requester_id, why_it_matters, severity | Unique per (need, requester), so support is idempotent. |
| embedding | owner_type (request, need_canonical), owner_id, model, text_hash, vector (float32 BLOB) | One vector per request and one canonical vector per need. |
| job | id, kind (intake, brief), ref_id, state (queued, running, done, failed), attempts, last_error, claimed_at, available_at | The queue (ADR 0007). |
| ai_run | id, step, model, prompt_version, input_tokens, output_tokens, cost_usd, latency_ms, outcome (ok, refusal, max_tokens, validation_error, provider_error, timeout), request_id or need_id | Written by the gateway for every call (CLAUDE.md rule 5). |
| event | id, entity_type, entity_id, kind, actor_type (ai, pm, requester, system), actor_id, payload, created_at | Append-only. The metrics are computed from it. |
| brief (should) | need_id, body, claims (each with a source id, quote and number), unverified_claims, ai_run_ids | Claims that fail verification are flagged, not shown as fact. |

**Request and link transitions.** A request is `linked` when a human (the requester or a PM) chose its need, and `auto_linked` when policy did.

| Event | Request status | Link change | Inbox tab |
|---|---|---|---|
| Saved | pending (job queued) | A claim creates a requester_claimed link, active | none |
| Worker claims the job | processing | none | none |
| Routed: auto-link | auto_linked | ai_auto, active; audit flag set | Auto-linked (read-only), plus Audit sample if sampled |
| Routed: gray zone | suggested | ai_suggested, proposed | Suggestions |
| Routed: new need | new_need | ai_new_need, active, to a new need (created_by ai); candidates labelled same_need or related → ai_related, related | none |
| Claim confirmed | linked | Claim stays active | none |
| Claim disputed | suggested | Claim becomes disputed (excluded from demand); the model's alternative, if any, is proposed | Disputed claims |
| AI failure (terminal) | needs_review (reason) | An active claim becomes disputed | Needs review |
| PM accepts a suggestion or a disputed claim | linked | That link becomes active; other proposed links become rejected | none |
| PM rejects | new_need, or linked if the PM links elsewhere | rejected; a new need or a pm_manual link is created | none |
| PM undoes an auto-link | suggested | undone; the next-best candidates are proposed | Suggestions |
| Audit verdict false_merge | suggested | audit_verdict set, link undone; the next-best candidates are proposed | Suggestions |
| PM links manually (any tab) | linked | pm_manual, active | none |
| PM relinks the last active request of an AI-created need, or merges two needs | linked | Old links undone, new links active | none; the emptied need becomes `merged` with merged_into_id |

**Audit sample** (F3). An auto-link is sampled when `sha256(request_id) mod 10 == 0`. The hash makes the sample about 10%, reproducible and testable. The PM gives each sampled link a verdict of `correct` or `false_merge`.

## 6. AI pipeline

| # | Step | Technique | Model | Deterministic | On failure |
|---|---|---|---|---|---|
| 1 | Redact | Regex for emails and phone numbers, applied at save (`redacted_text`) and again inside the gateway on every input of every call (brief, agent tool results, F7 drafts, candidate texts) | none | yes | not applicable |
| 2 | Embed | Local fastembed `bge-small` behind an `Embedder` interface | none (local) | yes | Retry the job; after N failures, needs_review |
| 3 | Retrieve | numpy cosine over request and canonical vectors; per need, take the best match; return the top 5 needs, plus the claimed need if there is one and it isn't already among them | none | yes | An empty backlog goes straight to new_need |
| 4 | Extract | Structured output (`messages.parse` with a Pydantic schema); text inside XML tags | Chosen by eval (ADR 0006); offline: heuristics | no | Provider error or timeout (transient): the job is retried with backoff, up to N=3 attempts, then needs_review. Inside the gateway: max_tokens gets one retry with a higher limit, and a validation error gets one retry. A second failure of either, or any refusal, is terminal: needs_review immediately, with the reason. |
| 5 | Adjudicate | Structured output: for each candidate, a label (same_need, related, different), a confidence, a rationale and quotes | Chosen by eval; offline: similarity thresholds (the baseline) | no | Same as step 4. A quote that isn't found verbatim in the request is dropped and flagged. |
| 6 | Route | Routing score and thresholds (section 8) | none | yes | not applicable |
| 7 | Enrich | Join the requester and account: segment, ARR, renewal date, pipeline | none | yes | Missing account: score without revenue; the gap is flagged |
| 8 | Score | The prioritization formulas (section 8) | none | yes | not applicable |

Model calls happen first. All results are then written in one transaction, so a retry never leaves partial state. ai_runs are written separately, so failed calls still count toward cost.

**Offline mode** (`AI_MODE=offline`, the default):
- Steps 4 and 5 use heuristics and the embedding baseline, and the UI labels their source as "offline baseline".
- The seed data also carries AI outputs recorded during `make seed-live`, labelled with their model and prompt version. The seed loader validates them through the same Pydantic schemas before persisting them. Reviewers therefore see real model output without an API key.

## 7. Human-in-the-loop policy

| Action | Automation level | Why |
|---|---|---|
| Suggest needs while typing | Automatic, no LLM | Cheap and instant; the requester decides |
| Requester claims "this is my need" | Automatic, then adjudicated; disputes go to the PM | Requesters over-claim, and an unchecked claim is a merge |
| Auto-link above T_auto | Automatic, labelled, one-click undo, 10% audited | High precision expected; the audit measures it |
| Link in the gray zone | Suggestion only; the PM decides | Errors there are costly and uncertain |
| Create a new need | Automatic | Cheap to merge later, and a merge is measured (M2 leakage) |
| AI failure | Goes to needs_review with the reason | AI never blocks a submission (CLAUDE.md rule 2) |
| Rate strategic fit (should) | Automatic, shown as a separate component with its rationale | Advisory; the PM sees it apart from demand |
| Need status (planned, declined, ...) | Human only | It is a product decision |
| Stakeholder messages (should) | AI drafts, the PM approves | The messages are external commitments |
| Thresholds and weights | Config, changed by a human after an eval run | The model judges, code decides (rule 1) |

## 8. Formulas (config at the repo root: config/routing.yaml, config/priorities.yaml, config/goals.yaml)

**Routing score**, for each candidate need *n* (ADR 0003):
- *L_n*: the adjudicator's label. The model's stated confidence is recorded and shown, but not used.
- *s_n*: the best cosine similarity between the request and any of the need's vectors.
- *f_n*: field agreement, the mean of (product_area matches, persona matches), so 0, 0.5 or 1.
- `score_n = 0` if *L_n* ≠ same_need. Otherwise `score_n = w_L + w_s · clip((s_n − s_min)/(s_max − s_min), 0, 1) + w_f · f_n`.
- Starting values: w_L 0.5, w_s 0.3, w_f 0.2. s_min and s_max are calibrated on the dev split.

**Policy**, on the best candidate *n\**:
- `score ≥ T_auto` (start high: 0.90): auto_linked.
- `T_suggest ≤ score < T_auto` (start: 0.60): suggested.
- Otherwise new_need. Candidates labelled same_need or related are still shown on the request as "possibly related" (links in state `related`). That is a suggestion only: it isn't in the inbox and doesn't count as demand.

A **claim** on need *m* (always among the candidates, see §6 step 3) is confirmed if `L_m = same_need` and `score_m ≥ T_suggest`. Otherwise it is disputed, and the inbox shows the model's alternative if there is one. The thresholds are chosen on the dev split (see test-plan.md).

The **baseline** uses the same policy code, with *L_n* replaced by `s_n ≥ s_dup`. That makes the comparison like for like.

**Prioritization**, per need. Only active links and supports count, and each account is counted once.
- **Demand** `D = min(1, log10(1 + R/1000) / log10(1 + R_cap/1000))`.
  - `R = Σ ARR_a` over customer accounts, plus `Σ p_win · pipeline_a` over prospects.
  - Starting values: `p_win` 0.2; `R_cap` $5M.
  - The log keeps one large account from dominating.
- **Urgency** `U = 0.6 · max severity weight + 0.4 · renewal share`.
  - Severity weights: blocker 1.0, workaround 0.5, nice-to-have 0.2.
  - Renewal share: the supporting ARR that renews within 90 days, divided by all supporting ARR.
- **Strategic fit** (should) `S = Σ_g weight_g · rating_g / 3`, over the goals in config/goals.yaml.
  - Each rating is 0 to 3 and comes with a rationale and a quote verified in code.
  - Until a need is rated, *S* is omitted, the other weights are renormalized, and the UI shows "not rated".
- **Priority** `= 100 · (w_D·D + w_U·U + w_S·S)`. Default weights: 0.40, 0.25, 0.35.
- **Popular** (unique supporters and accounts) and **strategic** (*S*) are shown next to the score, each with its inputs.

## 9. Cost per request by model option

Assumptions (estimates; measured values from ai_runs replace them):
- Extraction: about 2,000 input and 500 output tokens.
- Adjudication: about 3,000 input and 400 output tokens.
- Sonnet 5.5 thinking can't be disabled. It adds about 200 output tokens per call at low effort and about 800 at its default (high).
- Prices per million tokens (claude-api skill, cached 2026-09-25): Haiku 4.5 $1 in / $5 out; Sonnet 5.5 $2 / $10.
- The prompts are below the minimum cacheable length, so there is no caching discount.

| Config | Extract | Adjudicate | Calls | $ per request | $ per 1,000 |
|---|---|---|---|---|---|
| C0 Baseline (no LLM) | heuristics | similarity thresholds | 0 | 0 | 0 |
| C1 Haiku 4.5 everywhere | Haiku | Haiku | 2 | ~0.010 | ~10 |
| C2 Sonnet 5.5 for adjudication | Haiku | Sonnet 5.5 (high) | 2 | ~0.023 | ~23 |
| C3 Sonnet 5.5 low effort (the reference) | Sonnet 5.5 (low) | Sonnet 5.5 (low) | 2 | ~0.023 | ~23 |
| C4 Cascade (only if calibrated, ADR 0006) | Haiku | Haiku, then Sonnet 5.5 (high) when Haiku's routing score lands in the gray zone (~25%) | 2.25 | ~0.014 | ~14 |

Per need (should flows):
- Strategic fit: 1 call, about $0.01.
- Brief: 1 call, about $0.03.
- Overlap agent: at most 8 turns, about $0.10 at the cap.

At about 2,000 requests a month, the most expensive config costs about $46. That is small next to PM time (assumption A6: about 67 hours at 2 minutes per request). **Model choice is therefore decided on false merges and gray-zone size, not on price.**

## 10. Success metrics

The baselines are assumptions (marked A), because there is no real "before" data.

| ID | Metric | Definition (computed from `event`) | Assumed baseline | Level |
|---|---|---|---|---|
| M1 | PM triage effort | Share of processed requests with no PM-actor event, excluding audit verdicts; also reported as PM minutes per 100 requests (× 2 min) | 0% untouched today (A5) | must |
| M2 | Duplicate rate | Deflection: share of submissions that carry a claimed_need_id (from request-created events). Leakage: requests routed to new_need that a PM later relinks to an existing need | About 30% of incoming requests are duplicates (A7) | must |
| M3 | Decision-loop latency | Time from a need's status change to every supporter's update being approved | Median 14 days (A8) | should (needs F7) |
| M4 | False-merge rate (guardrail) | Audited auto-links marked false_merge ÷ audited auto-links, with a Wilson 95% interval; the undo rate on auto-links is reported as a lower bound | Target ≤ 3% (upper bound shown) | must |

Further guardrails shown in F8:
- Suggestion acceptance rate (target ≥ 80%; lower means the gray zone is too wide).
- needs_review rate.
- Cost per request and p95 latency per step.

## 11. Risks

| Risk | Mitigation |
|---|---|
| False merges hide demand and mislead updates | High T_auto, a disputed state for claims, a 10% audit (M4), one-click undo, only active links count |
| Synthetic data overstates quality | Hard cases written by hand first, a frozen test split, error bars, and the report says the data is synthetic |
| Prompt injection in request text | Text inside XML tags as data, structured output only, no write tools in intake (rule 3); the worst case is a wrong suggestion a human reviews or undoes |
| PII sent to the provider | Emails and phones redacted at save and again in the gateway on every call. Names aren't redacted (accepted risk, noted). |
| Provider outage or refusal | The queue retries with backoff, then needs_review; the app stays usable |
| Local embeddings miss paraphrases | recall@5 is its own metric; switch to Voyage below 90% (ADR 0002) |
| "The richest customer wins" | Log-scaled demand; popular and strategic shown separately; the PM decides status |
| Cost runaway | max_tokens per step, the agent step cap, ai_runs cost in F8 |
| Scope vs the 2-3 h guidance | Must and should levels; the agent is dropped first |

## 12. Non-goals

- Auth, SSO, multi-tenant.
- A real CRM, email or Slack integration (the CRM is a seeded table; delivery is in-app).
- Multilingual requests.
- Automatic need-status decisions.
- Fine-tuning.
- An LLM in the typing path.
- Load beyond one process (ADR 0005).

## 13. Assumptions

- **A1** All data is synthetic: Brightboard, its accounts and requests, and the eval cases are fictional. Eval numbers measure agreement with labels written by the author, not real customers.
- **A2** Requests are in English. The backlog stays under about 10K requests (brute-force search, ADR 0005).
- **A3** There is no auth. A persona switcher picks the requester or PM; one PM team.
- **A4** Token counts and prices are as in section 9 and are replaced by measured ai_runs values.
- **A5** Today a PM reads every request.
- **A6** About 2,000 requests a month, at 2 minutes of PM time each.
- **A7** About 30% of incoming requests duplicate an existing need.
- **A8** Supporters hear about a decision a median of 14 days after it is made.
- **A9** An offline demo shows baseline outputs for new submissions, and recorded live outputs for the seed data.
- **A10** Severity is self-reported by the requester; the extraction's severity signals are shown next to it but don't override it.
