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
| Product leader | Gets vote counts, or opinions | Gets demand, urgency and strategic fit shown separately, and a decision brief whose quotes and figures are verified in code (F6) |

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
| F0 | **Browse, search and support.** `GET /needs` gives text search, filters (status, product area, segment), sorting (priority, support, recent) and pagination. The need page shows member requests, supports and accounts, the score breakdown, and every AI value with its source, confidence and rationale. `POST /needs/{id}/support` records why it matters and a severity (nice_to_have, important, blocker). It is idempotent per requester and creates a claim that counts only once confirmed. | must | `api/test_needs_api.py`, `api/test_support_api.py` (passing); e2e GP1, GP4 |
| F1 | **Dedupe at the door (simple).** While the requester types, show the 5 closest needs, phrased as problem plus persona. This uses embeddings only and no LLM, under 300 ms server-side. "This is my need" calls the support endpoint, which creates a **requester claim** (a support in `claimed` state) that the intake workflow checks. Otherwise the requester submits a new request (`POST /requests`, saved as pending). | must | `api/test_requests_api.py`, `api/test_similar_api.py` (passing; embeddings only, never calls the gateway); e2e GP1; metric M2 |
| F2 | **Intake workflow** (background, after save): redact, embed, retrieve, extract, adjudicate, route, enrich, score (section 6). | must | Unit tests per deterministic step and for the worker; evals (retrieval recall@5 and adjudication; extraction is evaluated only through routing, not on its own); e2e GP2 (submit and track) and GP6 (provider failure) |
| F3 | **Confidence policy.** Routing score (section 8) produces: auto-link (labelled, undoable, 10% audit sample), suggestion in the inbox, or new need. A requester-claimed link is confirmed or disputed. | must | Unit tests (routing, policy, audit sampling); threshold choice in evals/REPORT.md; metric M4; e2e GP3 |
| F4 | **Prioritization** (ADR 0009). Demand, urgency, strategic fit and priority are computed in code when a need is read, with every component in the breakdown (must). Strategic fit is rated per goal by the model (strategic_fit_v1) against the goals in config/priorities.yaml, with the quote verified in code (should). Popular and strategic are shown separately, in the breakdown and in `GET /insights/quadrant`; each need is routed to the PM team owning its product area. | must (computed) / should (fit) | `unit/test_scoring.py`, `api/test_priority_api.py`, `unit/test_strategic_fit.py` (passing); strategic-fit agreement pending human labels (the eval hasn't run); e2e GP4 |
| F5 | **PM triage inbox.** Action tabs, audit sample first (at the locked threshold the gray zone is small, so the audit is most of the review work): Audit sample, Suggestions, Claim disagreements, Needs review (AI failed). Keyboard: j/k move, a accepts, r rejects (a held key never decides twice). A read-only Auto-linked tab lists every auto-link with an undo button and requires no action (CLAUDE.md rule 2). Both texts side by side, with accept, reject and undo (built); link manually, new need and merge needs are not built, so leakage (M2) stays 0. | must | `api/test_triage_api.py` (each transition in §5; links never deleted); e2e GP3; metric: suggestion acceptance rate |
| F6 | **Decision brief.** A workflow: gather the facts, make one LLM call, verify in code every quote, fact key, money figure and related need (counts in prose are not checked). An optional **overlap agent** finds needs this one overlaps with, blocks or depends on, using read-only search tools and a step cap; its findings feed the brief as cited evidence. As built ([ADR 0012](adr/0012-decision-briefs-bounded-agent-manual-loop.md)): `POST /needs/{id}/brief` queues a job; the agent (Haiku, tools `search_needs`, `get_need`, `get_trend`, at most 8 tool calls, 90 s) runs first; the brief (Sonnet, medium effort) gets figures as keyed facts; one repair round; failing claims shown flagged; "How this brief was built" shows every step and call. | should (built) | `unit/test_brief.py` (agent cap, read-only tools, cited and verbatim findings, money from the data, repair round, agent failure and timeout, trajectory; passing), `api/test_briefs_api.py` (passing), e2e GP7; live: [docs/examples/brief-sso.md](examples/brief-sso.md) (0 of 28 claims flagged, $0.043) |
| F7 | **Close the loop** ([ADR 0010](adr/0010-stakeholder-updates-ai-drafts-code-checks-pm-approves.md)). `PATCH /needs/{id}/status` takes a status, the PM's reason and an optional date, and saves at once. The worker then drafts (stakeholder_update_v1, FAST_MODEL; offline: a template) a personal update per supporter that refers to what they asked for, and a CS note per affected account. Code flags dates, timing and delivery promises the PM didn't make; approval re-checks and refuses while flagged. Approved messages go to a simulated outbox and the requester's need page, and each personal approval marks that supporter notified. | should (built) | `unit/test_commitments.py`, `api/test_updates_api.py` (passing); e2e GP5 `frontend/e2e/stakeholder-updates.spec.ts` (passing); metric M3 |
| F8 | **Metrics and AI Ops view.** Metrics M1-M4 and the guardrails (acceptance, needs-review rate, queue health), plus a summary of ai_runs: cost per request, p50/p95 latency per step, failure rate, by model and prompt version. | must | `api/test_workspace_api.py` (M1, M2, M4, queue), `api/test_updates_api.py` (M3); e2e GP5 checks M3 on the AI Ops page |

## 5. Data model

All tables live in SQLite (`backend/app/models.py`). Current state lives on the row (`request.need_id`, `support.link_status`, `aisuggestion.state`). How it got there lives in **`linkevent`**, an append-only history that undo, the audit sample and the AI audit trail read. Nothing an AI produced is ever deleted.

| Table | Key fields | Notes |
|---|---|---|
| account | id, name, segment (enterprise, mid_market, smb), arr, renewal_date, is_prospect, pipeline_value | The seeded "CRM". Prospects have arr 0 and a pipeline value. |
| requester | id, name, role, account_id | `account_id` is null for Brightboard staff (support, sales, CS, internal). No auth (A3). |
| need | id, title (problem plus persona), problem, persona, job_to_be_done, product_area, status (open, planned, in_progress, shipped, declined, merged), merged_into_id, created_by (ai, pm, seed), fit_status and fit_* job fields, fit_run_id (priority, demand, urgency and strategic fit are computed when read, not stored; ADR 0009) | Status is set by a PM, except `merged`. Merged needs are excluded from list, search, suggestions and retrieval. |
| request | id, requester_id, account_id (the customer, also when staff submit on its behalf), source (portal, support, sales, cs, internal), title, description, status (pending, processing, processed, needs_review), attempts, last_error, claimed_at, needs_review_reason, the AI fields (redacted_text, problem, persona, job_to_be_done, proposed_solution, product_area, severity_signal, extraction_confidence, extraction_rationale; null until processed), need_id, trace_id | Saved as pending before any model call. The row is the queue job (ADR 0007). |
| support | need_id, requester_id (unique together), why_it_matters, severity (nice_to_have, important, blocker), link_status (claimed, confirmed, disputed, rejected), check_attempts, check_started_at, check_error, review_reason | `POST /needs/{id}/support` is idempotent, including under a double click. It creates a **claim** that counts only once confirmed. A merged need returns 409. |
| aisuggestion | request_id or support_id, need_id, kind (duplicate, related, new_need), label, routing_score, model_confidence, rationale, quotes, state (proposed, applied, accepted, rejected, undone), audit_sample, audit_verdict (correct, false_merge), decided_by, decided_at, ai_run_id | Every routing decision, with its evidence. Only `proposed` suggestions appear in the action tabs. `related` ones are informational. |
| linkevent | action (link, unlink), actor (auto, pm, requester_claim), actor_id, need_id, request_id or support_id, suggestion_id, routing_score, reason, created_at | Append-only; never updated. One row per link or unlink. |
| airun | step, model, prompt_version, input_tokens, output_tokens, cost_usd, latency_ms, outcome, error, request_id or need_id, trace_id | Written by the gateway for every call (rule 5). |
| stakeholderupdate | need_id, kind (requester_update, cs_note), requester_id or account_id, status_change_id, body, original_body, approved_body, edited_by, flagged_commitments, status (draft, approved, discarded, superseded), approved_by, ai_run_id | Nothing goes out without approval (F7). A newer status change supersedes older drafts, which can't be approved. |
| needstatuschange | need_id, from_status, to_status, by, reason, target_date, drafts_status and drafts_* job fields | The PM's decision, saved at once; it is also the job that drafts the updates (ADR 0010). M3 starts here. |
| goalrating | need_id, ai_run_id, goal, rating (0-3), rationale, quote, quote_dropped | Append-only strategic-fit ratings per goal; `need.fit_run_id` points at the set in use (ADR 0009). |
| notification | need_id, requester_id, update_id, status_change_id, notified_at | Written when a personal update is approved: that supporter is marked notified. |
| outboxmessage | update_id, channel, recipient, subject, body | The simulated outbox: what would be sent, written only on approval. |

**Transitions.** `request.status` is the pipeline state. The routing outcome is `need_id` plus the suggestion and the LinkEvents.

| Event | request.status | Outcome rows | Inbox tab |
|---|---|---|---|
| Submitted | pending | none | none |
| Requester supports a need ("this is my need") | (no request) | support `claimed`; LinkEvent link by requester_claim | none |
| Worker claims the row | processing (attempts+1, claimed_at) | none | none |
| Routed: auto-link | processed | need_id set; suggestion `applied` (audit flag); LinkEvent link by auto, with the score | Auto-linked (read-only), plus Audit sample if sampled |
| Routed: gray zone | processed | suggestion `proposed`; need_id stays null | Suggestions |
| Routed: new need | processed | a new need (created_by ai); need_id set; suggestion `new_need` `applied`; LinkEvent link by auto; candidates labelled same_need or related → `related` suggestions | none |
| Claim checked: confirmed | (support) | support `confirmed`; suggestion `applied` | none |
| Claim checked: disputed | (support) | support `disputed` (still not counted); suggestion `proposed`, with the model's alternative if any | Disputed claims |
| AI failure (terminal) | needs_review (reason) | none | Needs review |
| Claim check fails (terminal) | (support) | support `disputed` with review_reason | Disputed claims |
| PM accepts | processed | need_id set; suggestion `accepted`; LinkEvent link by pm. For a claim: support `confirmed`. | none |
| PM rejects | processed | suggestion `rejected`; the request becomes its own need if nothing else is pending (LinkEvent by pm); linking it elsewhere by hand isn't built. For a claim: support `rejected`. | none |
| PM undoes a link (`POST /requests/{id}/unlink`) | processed | The request becomes its own need: LinkEvent unlink and link by pm (reason undo); suggestion `undone`; a sampled link with no verdict is recorded as false_merge. 409 if it is already the only request in its need | none |
| Audit verdict false_merge | processed | audit_verdict set; the request becomes its own need, as for an undo (reason "audit: false_merge") | none |
| An audit false_merge verdict moves the last request out of an AI-created need (built); a manual relink or merging two needs (not built) | processed | unlink + link LinkEvents; the emptied need becomes `merged` with no merged_into_id, so pending suggestions for it fail with need_gone instead of following the request | none |

**Audit sample** (F3). An auto-link is sampled when `sha256(seed:request_id) mod 10000 < rate × 10000` (seed and rate 10% in `config/routing.yaml`): random-looking, reproducible and testable. Decisions are compare-and-set: a second decision on the same item gets 409. Accepting into a need that has since been merged follows the merge. The PM marks each sampled link correct or false_merge.

## 6. AI pipeline

| # | Step | Technique | Model | Deterministic | On failure |
|---|---|---|---|---|---|
| 1 | Redact | Regex for emails and phone numbers. Stored as `redacted_text` before embedding, and applied again inside the gateway on every input of every call (candidate texts, strategic-fit inputs, F7 drafts) | none | yes | not applicable |
| 2 | Embed | Local fastembed `bge-small` behind an `Embedder` interface | none (local) | yes | Retry the row; after N failures, needs_review |
| 3 | Retrieve | numpy cosine over request and canonical vectors; per need, take the best match; return the top 5 needs, plus the claimed need if there is one and it isn't already among them | none | yes | An empty backlog goes straight to new_need |
| 4 | Extract | Structured output (`messages.create` with a JSON schema from the Pydantic model, validated in code; ADR 0008); text inside XML tags | Chosen by eval (ADR 0006); offline: heuristics | no | Provider error or timeout (transient): the job is retried with backoff, up to N=3 attempts, then needs_review. Inside the gateway: max_tokens gets one retry with a higher limit, and a validation error gets one retry. A second failure of either, or any refusal, is terminal: needs_review immediately, with the reason. |
| 5 | Adjudicate | Structured output: for each candidate, a label (same_need, related, different), a confidence, a rationale and quotes | Chosen by eval; offline: similarity thresholds (the baseline) | no | Same as step 4. A quote that isn't found verbatim in the request is dropped and flagged. |
| 6 | Route | Routing score and thresholds (section 8) | none | yes | not applicable |
| 7 | Enrich | Join the requester and account: segment, ARR, renewal date, pipeline | none | yes | Missing account: score without revenue; the gap is flagged |
| 8 | Score | The prioritization formulas (section 8) | none | yes | not applicable |

**As built (2026-10-07)** in `backend/app/ai/`:
- **Gateway.** It renders the versioned prompts: `extract_need_v1`, `adjudicate_v1`, `strategic_fit_v1` and `stakeholder_update_v1`. Untrusted text is redacted, then HTML-escaped inside its tags: `<request>`, `<why_it_matters>` and `<candidates>` for intake; `<need>` and `<requests>` for strategic fit (with `<goals>` from config); `<need>`, `<supporters>`, `<accounts>` and `<decision>` for stakeholder updates.
- **Clients.**
  - Live: `messages.create` with `output_config.format` (a JSON schema from the Pydantic model); the stop reason is checked first and the JSON is validated in our code (ADR 0008); a 30 s timeout and 2 SDK retries.
  - Tests: FakeLLM.
  - `AI_MODE=offline`: keyword heuristics for extraction, and the pipeline routes on similarity alone (the baseline).
- **Refusal fallbacks are off on purpose.** A refusal must reach needs_review, and one model per step keeps the evals clean.
- **Configuration.** Routing weights and thresholds are in `config/routing.yaml` → `llm`. Prioritization is in `config/priorities.yaml` and prices in `config/prices.yaml`.
- **Claims.** A claim is checked with `<request>` = "I support this existing need: <title>" and the requester's reason in `<why_it_matters>`. A claim with no reason goes to the inbox without a model call. Ids the model invents are ignored, and a candidate it skips counts as "different".

Model calls happen first. All results are then written in one transaction, so a retry never leaves partial state. ai_runs are written separately, so failed calls still count toward cost.

**Offline mode** (`AI_MODE=offline`, the default):
- Steps 4 and 5 use heuristics and the embedding baseline, and the UI labels their source as "offline baseline".
- `make seed` loads recorded Haiku 4.5 output (`backend/seed/snapshot.json`), built by `make snapshot` from the cached eval dev replay with no API calls. It is validated with the same Pydantic schemas, and refused if it no longer matches the locked config. The replay was teacher-forced (evals/snapshot.py), so the seed is real model output, not a simulated history. Reviewers therefore see real model output without an API key.

## 7. Human-in-the-loop policy

| Action | Automation level | Why |
|---|---|---|
| Suggest needs while typing | Automatic, no LLM | Cheap and instant; the requester decides |
| Requester claims "this is my need" | Automatic, then adjudicated; disputes go to the PM | Requesters over-claim, and an unchecked claim is a merge |
| Auto-link above T_auto | Automatic, labelled, one-click undo, 10% audited | High precision expected; the audit measures it |
| Link in the gray zone | Suggestion only; the PM decides | Errors there are costly and uncertain |
| Create a new need | Automatic | Undo exists. Merging needs isn't built, so M2 leakage stays 0 until it is |
| AI failure | Goes to needs_review with the reason | AI never blocks a submission (CLAUDE.md rule 2) |
| Rate strategic fit (should) | Automatic, shown as a separate component with its rationale | Advisory; the PM sees it apart from demand |
| Need status (planned, declined, ...) | Human only | It is a product decision |
| Stakeholder messages (should) | AI drafts, the PM approves | The messages are external commitments |
| Thresholds and weights | Config, changed by a human after an eval run | The model judges, code decides (rule 1) |

## 8. Formulas (config at the repo root: config/routing.yaml, config/priorities.yaml)

**Routing score**, for each candidate need *n* (ADR 0003):
- *L_n*: the adjudicator's label. The model's stated confidence is recorded and shown, but not used.
- *s_n*: the best cosine similarity between the request and any of the need's vectors.
- *f_n*: field agreement, the mean of (product_area matches, persona matches), so 0, 0.5 or 1.
- `score_n = 0` if *L_n* ≠ same_need. Otherwise `score_n = w_L + w_s · clip((s_n − s_min)/(s_max − s_min), 0, 1) + w_f · f_n`.
- Values: w_L 0.5, w_s 0.3, w_f 0.2, s_min 0.55, s_max 0.85. These are **placeholders, not calibrated**, kept on purpose (REPORT §4.3): recalibrating them would change the score and force a new T_auto.

**Policy**, on the best candidate *n\**:
- `score ≥ T_auto` (locked at 0.6953 from the evals, REPORT §4.2; it started at 0.90): auto-link (need_id set, suggestion `applied`).
- `T_suggest ≤ score < T_auto` (start: 0.60): suggested.
- Otherwise new_need. Candidates labelled same_need or related are still shown on the request as "possibly related" (`related` suggestions). That is a suggestion only: it isn't in the inbox and doesn't count as demand.

A **claim** (a support in `claimed` state) on need *m* is checked by the same workflow. It uses the support's why_it_matters as the text, and *m* is always among the candidates (§6 step 3). It is confirmed if `L_m = same_need` and `score_m ≥ T_suggest`. Otherwise it is disputed, and the inbox shows the model's alternative if there is one. The thresholds are chosen on the dev split (see test-plan.md).

The **baseline** (no LLM, and the app's offline mode) has no label and no extracted fields. It routes on the top similarity *s* alone, with its own thresholds tuned on dev (`config/routing.yaml` → `baseline`) and the same three bands. Results: evals/REPORT.md §1.

**Prioritization**, per need (ADR 0009). Computed when the need is read, never stored, so the renewal window follows the date and a weight change in config/priorities.yaml re-ranks on restart. Only member requests (need_id set) and confirmed supports count (a claim counts once the workflow confirms it or a PM accepts it), and each account is counted once.
- **Demand** `D = min(1, log10(1 + R/1000) / log10(1 + R_cap/1000))`.
  - `R = Σ ARR_a · w_seg(a)` over customer accounts, plus `Σ p_win · pipeline_a · w_seg(a)` over prospects (`is_prospect`).
  - Values: `p_win` 0.2; `R_cap` $5M; segment weights enterprise 1.0, mid-market 0.9, SMB 0.8 (placeholders for product leadership). An unknown segment gets the lowest weight and is flagged.
  - The log keeps one large account from dominating: ten times the revenue gives about 1.37 times the demand, and D is capped at 1.
  - A customer with no ARR or a prospect with no pipeline still counts as an account, adds 0 revenue, and is listed under `gaps`.
- **Urgency** `U = 0.6 · highest severity weight + 0.4 · [a supporting customer renews within 90 days]`.
  - Severity weights: blocker 1.0, important 0.5, nice_to_have 0.2, unknown 0. Sources: confirmed supports' severity and member requests' extracted severity signal.
  - The renewal term is yes/no (today through day 90, inclusive); prospects never renew. The renewing accounts are listed.
- **Strategic fit** (should) `S = Σ_g weight_g · rating_g / 3`, over the goals in config/priorities.yaml: enterprise readiness 0.40, retention 0.35, self-serve growth 0.25.
  - Each rating is 0 to 3, from strategic_fit_v1, with a one-sentence rationale and a quote verified in code (a quote not found in the requests is dropped and flagged; the rating stands).
  - Until every configured goal has a rating, S is omitted, the other weights are renormalized, and the UI shows the status: pending, failed (with the reason), stale (rated against goals that have changed) or not rated.
  - Rated when the need is created, and again when its supporting accounts cross 3 and 10, after a failure, or after the goals' text changes.
- **Priority** `= 100 · (w_D·D + w_S·S + w_U·U)`, 0 to 100. Weights: 0.40, 0.40, 0.20 (must sum to 1; config with negative weights, or with D and U both 0, is refused). Ties: more accounts first, then the older need.
- **Quadrant** (needs with S only): popular is `D ≥ 0.60` (a weighted R of about $165k), strategic is `S ≥ 0.50`. Clear win (both), strategic bet (strategic only), popular but off-strategy (popular only), park (neither). Shown with D, S and the account count, so popular and strategic stay visible separately.
- **Owner:** the PM team for the product area (config `owners.areas`; platform, data, reporting, growth), else product-triage.

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
- Brief: usually 1 call, 2 with a repair round; the worst case is 6 (a schema repair and a max_tokens retry on each of the two logical calls), and a transient failure re-runs the job up to 3 times. The live SSO brief's call cost $0.031 on Sonnet 5.5.
- Overlap agent: at most 9 Haiku turns (8 tool calls plus the answer); the live SSO run took 3 turns for $0.012.

At about 2,000 requests a month, the most expensive config costs about $46. That is small next to PM time (assumption A6: about 67 hours at 2 minutes per request). **Model choice is therefore decided on false merges and gray-zone size, not on price.**

## 10. Success metrics

The baselines are assumptions (marked A), because there is no real "before" data. Metrics are computed from `linkevent`, `aisuggestion`, `support` and the request timestamps (the "Definition" column names the rows).

| ID | Metric | Definition | Assumed baseline | Level |
|---|---|---|---|---|
| M1 | PM triage effort | Share of finished requests (processed or needs review) no PM had to touch: no PM LinkEvent or suggestion decision (audit verdicts excluded), no suggestion still waiting, not failed (A15); also reported as PM minutes per 100 requests (× 2 min) | 0% untouched today (A5) | must |
| M2 | Duplicate rate | Deflection: claims made at the door ÷ (claims + new requests) over the period. Leakage: requests routed to a new need that a PM later relinks to an existing need (LinkEvent unlink and link by pm) | About 30% of incoming requests are duplicates (A7) | must |
| M3 | Decision-loop latency | Per status change with personal updates: the time from the change to the last supporter's notification (their update approved); the median over completed changes. Changes with drafts still waiting are reported as pending | Median 14 days (A8) | measured (F7 built) |
| M4 | False-merge rate (guardrail) | Audited auto-links marked false_merge ÷ audited auto-links, with a Wilson 95% interval; the undo rate on auto-links is reported as a lower bound | Target ≤ 3% (upper bound shown) | must |

Further guardrails shown in F8:
- Suggestion acceptance rate (target ≥ 80%; lower means the gray zone is too wide).
- needs_review rate.
- Cost per request and p95 latency per step.

## 11. Risks

| Risk | Mitigation |
|---|---|
| False merges hide demand and mislead updates | The 10% audit sample (M4, measured on real traffic), one-click undo with LinkEvent history, and claims not counted until confirmed. Not the threshold: at the locked T_auto (0.6953) every same_need label auto-links, and the routing score doesn't separate errors (REPORT §4.2-4.3). |
| Synthetic data overstates quality | Hard cases written by hand first, a frozen test split, error bars, and the report says the data is synthetic |
| Prompt injection in request text | Text inside XML tags as data, structured output only, no write tools in intake (rule 3); the worst case is a wrong suggestion a human reviews or undoes |
| PII sent to the provider | Emails and phones redacted at save and again in the gateway on every call. Names aren't redacted (accepted risk, noted). |
| Provider outage or refusal | The queue retries with backoff, then needs_review; the app stays usable |
| Local embeddings miss paraphrases | recall@5 is its own metric; switch to Voyage below 90% (ADR 0002) |
| "The richest customer wins" | Log-scaled demand; popular and strategic shown separately; the PM decides status |
| Cost runaway | max_tokens per step, ai_runs cost in F8, per-client rate limits on `POST /requests` and support plus a write budget, and a daily model-spend ceiling the worker checks before claiming a job (ADR 0011). |
| Scope vs the 2-3 h guidance | Must and should levels; the decision brief and its agent (F6) were built late (#24), with no eval yet |

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
- **A10** Severity (nice_to_have, important, blocker) is self-reported on a support. The extraction's severity signal is shown next to it but doesn't override it.
- **A11** A request's description is optional (empty allowed) and capped at 5,000 characters; the title is required, 1-200 characters after trimming.
- **A12** Staff (requesters with no account) must name the customer `account_id` for support, sales and cs requests; internal requests may have none. A customer can only submit for their own account. Supports are always by the requester themselves, so a support's account is the requester's.
- **A13** Prospects' pipeline is weighted by their segment too, like customers' ARR (the request said "ARR times segment weight ... plus prospect pipeline"; one rule for both is simpler).
- **A14** "Accepted" support in the prioritization request means a claim a PM accepted from the inbox, which sets the support to confirmed; there is no separate accepted state.
- **A15** M1 counts a request as touched when a PM linked, unlinked or decided on it, when a suggestion for it still waits for a PM, or when it failed to needs_review; the denominator is every finished request (processed or needs review). M2 deflection counts every support, since each starts as a claim at the door; leakage counts only PM links without a reason (undo and false-merge moves carry one), so it stays 0 until a manual relink action exists.
