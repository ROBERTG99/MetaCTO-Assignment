# Requirements traceability

Source of truth: [assignment.md](assignment.md) (verbatim). Every sentence in it that creates an obligation has a row below.
IDs: R = explicit requirement, Q = question the Loom must answer, D = design commitment for the AI and production-readiness bar.
Status is `todo` or `done`. A row is `done` only when its proof exists. Last updated: 2026-10-07.

## Matrix

Proof references use planned names from [test-plan.md](test-plan.md): `unit/...` and `api/...` live under `backend/tests/`, GP1-GP6 are the e2e golden paths, and evals report in `evals/REPORT.md`. Spec sections are written §N.

### Setup and process

| ID | Requirement | How we satisfy it | How we prove it | Status |
|---|---|---|---|---|
| R1 | Create a public Git repository. | github.com/ROBERTG99/MetaCTO-Assignment, visibility public. | `gh repo view --json visibility` returns PUBLIC (checked 2026-10-07). | done |
| R2 | Set up your development environment. | `make setup` installs backend (uv) and frontend (npm) dependencies, downloads the embedding model and Playwright's Chromium; the README lists prerequisites. | README "Run it" section; the CI job runs setup from a clean checkout (D6). | todo |
| R3 | Before writing any code, open Claude Code in the project root and use the given CLAUDE.md prompt as the first prompt. | CLAUDE.md lines 1-3 hold the rule word for word, committed before any code. See T2 for the caveat. | `head -3 CLAUDE.md`; `git log` shows b67880f (CLAUDE.md) before any code commit; prompts.txt entries #1-#2. | done |
| R4 | Append every prompt to prompts.txt with an ISO 8601 timestamp and a brief summary of the response; create it if missing; keep it updated in all sessions. | CLAUDE.md rule, backed by hooks: raw audit trail, append-only guard, and a Stop gate that sends a turn back when it has no entry. | prompts.txt; prompts.audit.jsonl; `make check-hooks` (29 hook tests). | done |

### Product

| ID | Requirement | How we satisfy it | How we prove it | Status |
|---|---|---|---|---|
| R5 | Design and build an AI-first Feature Intelligence System that turns unstructured feature requests into clear, actionable product decisions. | Distill: the intake workflow turns raw requests into deduplicated, need-centric, scored needs, and the PM inbox turns those into decisions (spec §1, §4). | e2e GP1-GP4 (written before the pages; failing until they exist), plus the planned provider-failure and metrics paths; evals/REPORT.md. | todo |
| R6 | Users can submit and discover requests, and AI is a core part of how the system solves the problem: decide how AI fundamentally improves the workflow. | Every submission goes through the pipeline (F2, F3). The PM works from an inbox of exceptions instead of reading the stream (spec §3; ADR 0001). | Metric M1 (`api/test_workspace_api.py`); evals/REPORT.md (baseline vs LLM); e2e GP3 (the PM's exception inbox). | todo |
| R7 | Submit a feature request with a title and description. | Submit form and `POST /requests`. The request row is saved as pending before any model call; the row is the job (ADR 0007). | `api/test_requests_api.py` (saved before any model call; saved when the provider fails); e2e GP2 passing (`frontend/e2e/submit-and-track.spec.ts`); the planned provider-failure path. | done |
| R8 | View and discover existing requests. | Need list, search, and suggestions while typing (F0, F1). | `api/test_needs_api.py` (list, search, suggest never calls the gateway); e2e GP1; e2e GP1 passing (`frontend/e2e/discover-and-support.spec.ts`) | done |
| R9 | Express interest in or support for a request. | `POST /needs/{id}/support` with why and a severity, idempotent per requester. It is a claim that counts once the intake workflow confirms it (F0, F1). | `api/test_support_api.py`; `unit/test_pipeline.py` (claim confirmed vs disputed); `api/test_triage_api.py`; e2e GP1 (passing). | done |
| R10 | Understand how requests are grouped, evaluated or prioritized. | The need page shows member requests, the score breakdown with its inputs, popular and strategic shown separately, and every AI value with its source, confidence and rationale (F0, F4, spec §8, [ADR 0009](adr/0009-weighted-priority-computed-on-read.md)). API done: every need in `GET /needs` carries its breakdown (each component's inputs, points, weights, goal ratings with rationale, quote, model and prompt version, quadrant, owner); `GET /insights/quadrant` separates popular from strategic. | [unit/test_scoring.py](../backend/tests/unit/test_scoring.py), [api/test_priority_api.py](../backend/tests/api/test_priority_api.py) (incl. a config-only weight change re-ranking), [unit/test_strategic_fit.py](../backend/tests/unit/test_strategic_fit.py); strategic-fit agreement in [REPORT §5](../evals/REPORT.md); `unit/test_policy.py`; e2e GP4 (`frontend/e2e/pm-priorities.spec.ts`: quadrant, breakdown whose points add up to the score; failing until the page exists); e2e GP4 passing (`frontend/e2e/pm-priorities.spec.ts`) | done |
| R11 | Identify a high-value point in the request lifecycle and design an AI-powered solution around it. | Intake: dedupe and need extraction at the moment duplicates enter (spec §1; ADR 0002). | evals/REPORT.md: C0 baseline vs LLM configs on the hard slices. | todo |
| R12 | Include two or three success metrics. | M1 triage effort, M2 duplicate rate, M3 decision-loop latency (should), plus M4 false-merge rate as the guardrail (spec §10). | `api/test_workspace_api.py` (AI Ops and M1, M2, M4); e2e GP5 (M3 measured after a status change). | done |
| R13 | Clearly explain the agent or AI technology selected and why. | ADRs 0001 (workflow and one agent), 0002 (retrieval and LLM), 0006 (models by eval); a README section on the AI architecture. | docs/adr/0001, 0002, 0006; README. | todo |

### Submission

| ID | Requirement | How we satisfy it | How we prove it | Status |
|---|---|---|---|---|
| R14 | Push the code to GitHub; the repository is public. | Push after every commit; check visibility before sending. | `gh repo view --json visibility` on submission day. | todo |
| R15 | Complete within 2 business days. | Plan to the deadline (T3). | The last commit date is on or before the deadline. | todo |
| R16 | Send the submission to both addresses in the brief. | Robert sends it. | Sent email (manual checklist item). | todo |
| R17 | Share the repository URL. | Included in the email and the README. | Sent email. | todo |
| R18 | Record a ~5 minute Loom walking through the project running locally. | A timed talk track; the demo runs on the local stack (T6). | The Loom link in the README. | todo |
| R19 | Loom: product overview. | Opening segment, from spec §1-§3. | Loom. | todo |
| R20 | Loom: features implemented. | Demo of GP1-GP3 and GP6. | Loom. | todo |
| R21 | Loom: AI-powered capability. | Live intake: a duplicate auto-linked, the need extracted, the score explained. | Loom; evals/REPORT.md. | todo |
| R22 | Loom: architecture decisions and technical tradeoffs. | Summary of ADRs 0001-0007. | Loom; docs/adr/. | todo |
| R23 | Loom: how AI was used throughout the development process. | prompts.txt, hooks, test-first, review subagent (D7). | Loom; prompts.txt. | todo |
| R24 | Include the Loom link in the submission. | Included in the email and the README. | Sent email; README. | todo |

### Questions the Loom must answer

Each answer is written down first, so the Loom can summarize it and point to the doc.

| ID | Requirement | How we satisfy it | How we prove it | Status |
|---|---|---|---|---|
| Q1 | Which business problem you prioritized and why. | Intake, where duplicates and unclear needs start (spec §1). | spec §1; Loom. | todo |
| Q2 | Who benefits from your solution. | PMs, requesters, CS and sales, product leaders (spec §2). | spec §2; Loom. | todo |
| Q3 | Why AI is appropriate for the problem. | Telling needs apart is about meaning; the LLM must beat the embedding baseline on the hard slices (ADR 0002). | evals/REPORT.md; ADR 0002; Loom. | todo |
| Q4 | How AI changes the workflow rather than just enhancing the interface. | The PM handles exceptions instead of the stream (spec §3, §7). | spec §3; metric M1; Loom. | todo |
| Q5 | Which agent, model, framework or AI architecture you chose and why. | A workflow, with one agent only where the path is open; models chosen per step by eval (ADRs 0001, 0006). | ADRs 0001, 0006; evals/REPORT.md; Loom. | todo |
| Q6 | Where human judgment remains necessary. | The HITL policy (spec §7; ADR 0004). | spec §7; e2e GP3 (accept a suggestion, check an audited auto-link, undo); Loom. | todo |
| Q7 | How you would measure business impact. | M1-M4, instrumented through the event log (spec §10). | `api/test_workspace_api.py`; the AI Ops page (`/ops`); the planned e2e metrics path; Loom. | todo |
| Q8 | Assumptions, risks and tradeoffs. | Spec §11 (risks), §13 (assumptions); each ADR's consequences. | spec §11, §13; docs/adr/; Loom. | todo |

### Design commitments

| ID | Requirement | How we satisfy it | How we prove it | Status |
|---|---|---|---|---|
| D1 | Model and threshold choices made from evals, against a no-LLM baseline. | Baseline and three LLM strategies on a frozen test set (150, 17 handwritten) and a dev replay. Haiku 4.5 for both steps chosen on dev by the simpler-wins rule and confirmed on test (91.3% vs 74.7%); only Haiku clearly beats the baseline. T_auto = 0.6953 (degenerate sweep, stated as such). Locked in `config/routing.yaml`, citing the report. | [REPORT §3](../evals/REPORT.md#3-model-strategy-comparison-2026-10-07), [§4](../evals/REPORT.md#4-decisions-2026-10-07); [config/routing.yaml](../config/routing.yaml); [ADR 0006](adr/0006-per-step-model-choice-by-eval.md), [ADR 0004](adr/0004-confidence-gated-reversible-automation.md); [evals/tests/test_dataset.py](../evals/tests/test_dataset.py) (freeze), [test_llm.py](../evals/tests/test_llm.py), [test_compare.py](../evals/tests/test_compare.py). | done |
| D2 | A model cascade (cheap model first, stronger model only for ambiguous cases) if the evals justify it. | Evaluated on dev, confirmed on test, rejected: on the band a cascade would escalate, Sonnet is the weaker judge (dev 18/25 vs 24/25), and the cascade (72.6%) loses to Sonnet-low (74.2%) and Haiku alone (82.3%). Not built. | [REPORT §3 cascade decision](../evals/REPORT.md#cascade-decision-not-worth-building), [§4.1](../evals/REPORT.md#41-strategy-haiku-45-for-both-extraction-and-adjudication-the-cascade-stays-unbuilt); [ADR 0006](adr/0006-per-step-model-choice-by-eval.md); [evals/compare.py](../evals/compare.py), [test_compare.py](../evals/tests/test_compare.py). | done |
| D3 | Decision briefs whose quotes and numbers are verified in code. | The F6 brief workflow, with a verifier in code; the agent's findings are verified too (should). | `unit/test_verify.py`; brief eval slice with fabricated quotes and numbers. | todo |
| D4 | The success metrics instrumented in the product, not just described. | `GET /metrics` and the AI Ops page compute M1, M2, M3 and M4 and the guardrails (acceptance, needs-review rate, cost, latency) on read from the rows the app writes: linkevent, aisuggestion, support, needstatuschange, notification, ai_runs (F8, F7; spec §10). | [api/test_workspace_api.py](../backend/tests/api/test_workspace_api.py) (M1, M2, M4), [api/test_updates_api.py](../backend/tests/api/test_updates_api.py) (M3 from real timestamps); e2e GP3 (audit) and GP5 (M3 shows a value after the flow). | done |
| D5 | Runs without an API key (offline mode) with one command. | `AI_MODE=offline` by default (baseline plus recorded live outputs in the seed); one make target (planned `make demo`: setup, seed, dev); SQLite and the in-process queue need no services (ADRs 0005, 0007). | CI runs `make setup` and `make seed` from a clean checkout with no API key, then e2e offline. `make demo` (setup, seed, dev) is the one command for humans. | todo |
| D6 | CI with unit, contract, hook and end-to-end tests. | GitHub Actions runs `make check`, the contract diff, `make eval-offline` and `make e2e` (test-plan §1). | A green CI run on main. | todo |
| D7 | An AI-assisted development process with enforced logging, test-first work and a review subagent. | CLAUDE.md, the .claude/ hooks, the tdd skill and the reviewer agent. | prompts.txt (red to green, reviewer verdicts); prompts.audit.jsonl; hook tests; git history. | done |
| D8 | Keep stakeholders informed (brief: "keep stakeholders informed about decisions and progress", "help communicate decisions back to stakeholders"). | F7, [ADR 0010](adr/0010-stakeholder-updates-ai-drafts-code-checks-pm-approves.md): a status change with a reason; AI drafts a personal update per supporter and a CS note per account; code flags commitments; nothing is sent without PM approval; M3 measured. | [unit/test_commitments.py](../backend/tests/unit/test_commitments.py), [api/test_updates_api.py](../backend/tests/api/test_updates_api.py), e2e GP5 (passing). Open: no eval for stakeholder_update_v1 yet (CLAUDE.md rule 7); safety rests on the code check and human approval. | todo |

## What separates a great submission from an adequate one

They say they care more about how AI is incorporated than about the feature, and they evaluate "real-world agentic systems" and "production-ready" thinking. Reading 50 of these, the signal is:

1. AI moves work, not pixels. Adequate: a "summarize" button or an AI tag on a voting board. Great: the PM's job changes (fewer items to read, decisions prepared, exceptions surfaced), and the demo shows that change.
2. Evidence over assertion. Why this model, why this threshold, why AI at all: answered with numbers against a no-LLM baseline, including cost and latency.
3. Human in the loop by design. Confidence and rationale on every AI value, a clear line between automatic and suggested, and every AI action can be undone.
4. It behaves well when the AI fails. Provider down, refusal, prompt injection in user text, PII. The submission still saves and the request goes to a queue.
5. The system can be observed. Every model call is logged with cost and outcome, and the success metrics are measured rather than just named.
6. A precise word for the architecture. Knowing when a fixed workflow beats an agent loop (determinism, cost, audit) and saying so is more "agentic-systems thinking" than an unnecessary agent.
7. Finished and coherent. One golden path that works, runs with one command and is tested beats a wide, half-working build.
8. The process is visible. prompts.txt shows judgment (pushing back, verifying, test-first), not only "build X". The Loom is tight and on time.

## Constraints and traps

| ID | Trap | What we do |
|---|---|---|
| T1 | Time guidance is roughly 2-3 hours. The architecture in CLAUDE.md (FastAPI, React, evals, CI, e2e) is well beyond that. Reviewers weigh depth against scope, and an unfinished ambitious build loses. | Set a cut line before building (see "Beyond the brief"). Finish the golden path first. |
| T2 | The brief says the CLAUDE.md prompt must be the first prompt, from the project root, before any code. In prompts.txt, #1 is the clone (run from the parent folder) and #2 is the CLAUDE.md prompt, logged as a paraphrase. The CLAUDE.md wording is exact and no code came before it. | Don't rewrite the log (append-only). Say it plainly in the README or Loom if asked. |
| T3 | The deadline is 2 business days from receiving the brief. The receipt date isn't in the repo. | If it arrived Wed 2026-10-07, the deadline is Fri 2026-10-09. Robert to confirm. |
| T4 | The repo is public. Everything committed is public: prompts.txt, prompts.audit.jsonl, and docs/assignment.md, which contains the two reviewers' email addresses. | No secrets in history (redaction hook, .env ignored). Robert decides whether publishing the brief verbatim is fine. |
| T5 | ~5 minutes for 5 sections and 8 questions. | A timed script. Depth lives in the docs, and the Loom points to them. |
| T6 | The Loom shows the project running locally. An offline demo would show baseline output, not the LLM's. | Record with AI_MODE=live, which costs money and needs Robert's go. The seed data carries outputs recorded from a live run, so the offline run also shows real model output (spec A9). |
| T7 | "Agentic systems": a fixed pipeline is a workflow, not an agent. | Answer Q5 explicitly: why a workflow here, and where an agent loop would or wouldn't fit. |
| T8 | prompts.txt is read by the reviewers. The brief asks for a "brief summary". Our summaries are long, the entry format changed twice (#1-#2, #3, #4 onward), and the audit file also records subagent hand-back messages. | Keep summaries short from now on. Explain the audit file in the README. |
| T9 | "Users" includes non-PM submitters, and "express interest" must exist even if dedupe replaces voting. | Keep R9 explicit and tested. |
| T10 | The submission goes by email to two addresses and needs both the repo URL and the Loom link. | Use the R14-R24 rows as the send checklist. |

## Beyond the brief

The brief explicitly encourages going past the minimum ("extend the system ... production-ready and polished"), so extensions are in scope. The real limits are the 2-3 hour guidance and the deadline (T1, T3). Flags:

| Item | Brief asks for | Beyond by | Recommendation |
|---|---|---|---|
| D2 cascade | Nothing; model choice is only something to explain (Q5) | Clearly | Keep it conditional on the evals, as written. Don't build it until D1 shows an ambiguous band worth it. |
| D3 verified decision briefs | Decision briefs are one of nine "might" options | Clearly | Build only if decision briefs are part of the chosen AI point (R11). Otherwise defer. |
| D6 CI with contract and e2e | Nothing about CI or tests | Clearly | The highest time cost. Minimum: CI runs unit and hook tests plus one e2e golden path. Contract test only as a type-drift check. |
| D1 evals vs baseline | "Why AI is appropriate" and "why this model" (Q3, Q5) | Mildly | Keep it, at about 150 labelled pairs weighted toward the hard cases: fewer can't separate the model configurations (ADR 0006). It's the strongest answer to Q3 and Q5. |
| D4 instrumented metrics | Metrics and "how you *would* measure" (R12, Q7) | Mildly | Keep it to one metrics endpoint and view. |
| D5 offline one command | A locally running project (R18) | Mildly | Keep. It lets reviewers run the project without a key. |
| D7 AI-assisted process | Prompt logging (R4) and "how AI was used" (R23) | Mildly | Keep; already in place. |
| CLAUDE.md extras | Not asked | Clearly | PII redaction, prompt-injection handling, ai_runs cost ledger, auto-link with undo, route and enrich steps, generated API types, ADRs. These support Q6 and Q8 and the "production-ready" bar, but each one costs time. Decide the cut line in the spec. |
