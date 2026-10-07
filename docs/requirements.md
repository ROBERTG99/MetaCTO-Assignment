# Requirements traceability

Source of truth: [assignment.md](assignment.md) (verbatim). Every sentence in it that creates an obligation has a row below.
IDs: R = explicit requirement, Q = question the Loom must answer, D = design commitment for the AI and production-readiness bar.
Status is `todo` or `done`. A row is `done` only when its proof exists. Last updated: 2026-10-07.

## Matrix

### Setup and process

| ID | Requirement | How we satisfy it | How we prove it | Status |
|---|---|---|---|---|
| R1 | Create a public Git repository. | github.com/ROBERTG99/MetaCTO-Assignment, visibility public. | `gh repo view --json visibility` returns PUBLIC (checked 2026-10-07). | done |
| R2 | Set up your development environment. | `make setup` installs backend (uv) and frontend (npm) dependencies; README lists prerequisites. | README run steps work from a clean checkout; CI (D6) runs them. | todo |
| R3 | Before writing any code, open Claude Code in the project root and use the given CLAUDE.md prompt as the first prompt. | CLAUDE.md lines 1-3 hold the rule word for word, committed before any code. See T2 for the caveat. | `head -3 CLAUDE.md`; `git log` shows b67880f (CLAUDE.md) before any code commit; prompts.txt entries #1-#2. | done |
| R4 | Append every prompt to prompts.txt with an ISO 8601 timestamp and a brief summary of the response; create it if missing; keep it updated in all sessions. | CLAUDE.md rule, backed by hooks: raw audit trail, append-only guard, and a Stop gate that sends a turn back when it has no entry. | prompts.txt; prompts.audit.jsonl; `make check-hooks` (29 hook tests). | done |

### Product

| ID | Requirement | How we satisfy it | How we prove it | Status |
|---|---|---|---|---|
| R5 | Design and build an AI-first Feature Intelligence System that turns unstructured feature requests into clear, actionable product decisions. | Distill: an AI intake pipeline turns raw requests into deduplicated, need-centric, scored items, and a PM queue turns those into decisions. | docs/spec.md; end-to-end golden path from submission to decision. | todo |
| R6 | Users can submit and discover requests, and AI is a core part of how the system solves the problem: decide how AI fundamentally improves the workflow. | Every submission goes through the pipeline. The PM works from an AI-prepared queue instead of reading raw requests. | Spec section "How AI changes the workflow"; eval report (D1); e2e spec. | todo |
| R7 | Submit a feature request with a title and description. | Submit form and API. The request is saved before any model call, and AI never blocks it. | API test (saved even when the model fails); e2e spec. | todo |
| R8 | View and discover existing requests. | List and search, grouped by underlying need. | API tests for list and search; e2e spec. | todo |
| R9 | Express interest in or support for a request. | A support action on each request or need. A duplicate submission linked to an existing need also counts as support and keeps the submitter's context. | API tests (support is idempotent per user; a linked duplicate adds support); e2e spec. | todo |
| R10 | Understand how requests are grouped, evaluated or prioritized. | Each item shows its group, a score breakdown using the weights in config/priorities.yaml, and every AI value with its source, confidence and rationale. | Scoring unit tests; e2e check that the breakdown and rationale are visible. | todo |
| R11 | Identify a high-value point in the request lifecycle and design an AI-powered solution around it. | Intake: duplicates are created and triage cost starts at submission, so dedupe and need extraction happen there. To be confirmed in an ADR. | ADR; eval report (D1). | todo |
| R12 | Include two or three success metrics. | Pick 3 in the spec, for example duplicate rate, time to triage and PM override rate of AI suggestions. | docs/spec.md metrics section; instrumented by D4. | todo |
| R13 | Clearly explain the agent or AI technology selected and why. | ADR on the AI architecture plus a README section. | docs/adr/; README. | todo |

### Submission

| ID | Requirement | How we satisfy it | How we prove it | Status |
|---|---|---|---|---|
| R14 | Push the code to GitHub; the repository is public. | Push after every commit; check visibility before sending. | `gh repo view --json visibility` on submission day. | todo |
| R15 | Complete within 2 business days. | Plan to the deadline (T3). | Last commit date is on or before the deadline. | todo |
| R16 | Send the submission to both addresses in the brief. | Robert sends it. | Sent email. | todo |
| R17 | Share the repository URL. | Included in the email. | Sent email. | todo |
| R18 | Record a ~5 minute Loom walking through the project running locally. | A timed talk track; the demo runs on the local stack (T6). | Loom link. | todo |
| R19 | Loom: product overview. | Opening segment. | Loom. | todo |
| R20 | Loom: features implemented. | Demo of the golden path. | Loom. | todo |
| R21 | Loom: AI-powered capability. | Live intake: a duplicate auto-linked, need extracted, score explained. | Loom. | todo |
| R22 | Loom: architecture decisions and technical tradeoffs. | Summary of the ADRs. | Loom; docs/adr/. | todo |
| R23 | Loom: how AI was used throughout the development process. | prompts.txt, hooks, test-first, review subagent (D7). | Loom; prompts.txt. | todo |
| R24 | Include the Loom link in the submission. | Included in the email and the README. | Sent email; README. | todo |

### Questions the Loom must answer

Each answer is written down first (spec, ADRs, README), so the Loom can summarize it and point to the doc.

| ID | Requirement | How we satisfy it | How we prove it | Status |
|---|---|---|---|---|
| Q1 | Which business problem you prioritized and why. | Duplicates and unclear needs at intake drive the triage cost (R11). | docs/spec.md "Problem"; Loom. | todo |
| Q2 | Who benefits from your solution. | PMs (triage time), submitters (status and feedback), product leaders (decisions). | docs/spec.md "Users"; Loom. | todo |
| Q3 | Why AI is appropriate for the problem. | Paraphrase-level duplicates and need extraction are language tasks; evals show the gain over a no-LLM baseline. | evals/REPORT.md (D1); Loom. | todo |
| Q4 | How AI changes the workflow rather than just enhancing the interface. | The PM reviews AI-prepared decisions and exceptions instead of reading every request. | docs/spec.md "Workflow before and after"; Loom. | todo |
| Q5 | Which agent, model, framework or AI architecture you chose and why. | A deterministic pipeline with model steps through one gateway; models chosen from evals (D1, D2). | ADR; Loom. | todo |
| Q6 | Where human judgment remains necessary. | Low-confidence links, priority decisions, and anything the AI flags; every AI action can be undone. | docs/spec.md; e2e undo test. | todo |
| Q7 | How you would measure business impact. | The R12 metrics, instrumented (D4). | docs/spec.md metrics; metrics view. | todo |
| Q8 | Assumptions, risks and tradeoffs. | Recorded as they happen. | docs/spec.md "Assumptions"; ADR consequences; Loom. | todo |

### Design commitments

| ID | Requirement | How we satisfy it | How we prove it | Status |
|---|---|---|---|---|
| D1 | Model and threshold choices made from evals, against a no-LLM baseline. | A labelled dataset with dev and test splits. `make eval-offline` (baseline) and `make eval` (LLM). Thresholds are calibrated on dev only. | evals/REPORT.md: baseline vs LLM, with cost and latency. | todo |
| D2 | A model cascade (cheap model first, stronger model only for ambiguous cases) if the evals justify it. | The fast model handles clear cases; the smart model handles only the ambiguous band. Adopted only if the report shows it wins on quality per cost; otherwise an ADR records why not. | evals/REPORT.md comparison; ADR. | todo |
| D3 | Decision briefs whose quotes and numbers are verified in code. | Each quote must appear verbatim in a source request, and each number must match the database. Anything that fails is dropped and flagged. | Verifier unit tests; eval cases with fabricated quotes and numbers. | todo |
| D4 | The success metrics instrumented in the product, not just described. | Timestamps and events (submitted, triaged, linked, unlinked, overridden), plus a metrics endpoint and view. | API tests for each metric calculation. | todo |
| D5 | Runs without an API key (offline mode) with one command. | AI_MODE=offline by default with a deterministic fake model and baseline; one make target sets up, seeds and runs. | CI runs it from a clean checkout; e2e runs offline. | todo |
| D6 | CI with unit, contract, hook and end-to-end tests. | GitHub Actions runs `make check` and `make e2e`. The contract test fails if the frontend types drift from the OpenAPI schema. | A green CI run on main. | todo |
| D7 | An AI-assisted development process with enforced logging, test-first work and a review subagent. | CLAUDE.md, .claude/ hooks, the tdd skill and the reviewer agent. | prompts.txt (red to green, reviewer verdicts); prompts.audit.jsonl; hook tests; git history. | done |

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
| T6 | The Loom shows the project running locally. An offline demo would show fake AI output. | Record with AI_MODE=live, which costs money and needs Robert's go. Reviewers can still run offline (D5). |
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
| D1 evals vs baseline | "Why AI is appropriate" and "why this model" (Q3, Q5) | Mildly | Keep it small: about 40 labelled cases. It's the strongest answer to Q3 and Q5. |
| D4 instrumented metrics | Metrics and "how you *would* measure" (R12, Q7) | Mildly | Keep it to one metrics endpoint and view. |
| D5 offline one command | A locally running project (R18) | Mildly | Keep. It lets reviewers run the project without a key. |
| D7 AI-assisted process | Prompt logging (R4) and "how AI was used" (R23) | Mildly | Keep; already in place. |
| CLAUDE.md extras | Not asked | Clearly | PII redaction, prompt-injection handling, ai_runs cost ledger, auto-link with undo, route and enrich steps, generated API types, ADRs. These support Q6 and Q8 and the "production-ready" bar, but each one costs time. Decide the cut line in the spec. |
