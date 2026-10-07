# Project Rules
## Prompt Logging
Every time you receive a new instruction or prompt, append it to prompts.txt in the project root with a timestamp (ISO 8601) and a brief summary of what you did in response. Create the file if it doesn't exist. Keep this log updated throughout all sessions.
- Hooks in .claude/hooks/ back this rule up: every raw prompt is also written to prompts.audit.jsonl, edits that would rewrite prompts.txt or prompts.audit.jsonl are blocked, and a turn that ends without its entry is sent back once to write it. They don't replace the rule; an interrupted turn isn't checked.

----Project
Distill: an AI-first feature intelligence system. It turns unstructured feature requests into deduplicated, need-centric, prioritized product decisions, with a PM in the loop. It is a take-home assessment: AI-first product thinking, architecture and tradeoffs, production readiness, and how AI was used to build it all matter.
- The assignment, verbatim: docs/assignment.md. It is the source of requirements.
- The project root is the git repo cloned from GitHub; prompts.txt and CLAUDE.md live at its root.
- Traceability: docs/requirements.md maps every requirement to a feature, a test or eval, and a status. Keep it current.
- Spec: docs/spec.md. Decisions: docs/adr/. Test strategy: docs/test-plan.md. Read the relevant section before starting a feature.

----Architecture map
- backend/: Python 3.12, FastAPI, SQLModel + SQLite (WAL mode), Pydantic v2, managed with uv.
  - app/api/: thin HTTP routes. app/services/: business logic. app/models.py: tables.
  - app/ai/gateway.py: the only module that calls a model provider.
  - app/ai/prompts/: versioned prompt files (`<step>_v<N>.md`).
  - app/ai/pipeline.py: intake workflow (redact, embed, retrieve, extract, adjudicate, route, enrich, score).
  - app/scoring.py: deterministic priority math; weights in config/priorities.yaml.
- frontend/: React, TypeScript (strict), Vite, Tailwind, TanStack Query; API types generated from OpenAPI; Playwright specs in e2e/.
- evals/: datasets, runner, REPORT.md.
- Path-scoped rules in .claude/rules/ load when you work on AI code, tests or the frontend.

-----Commands
- `make setup` · `make dev` (API :8000, web :5173) · `make seed` · `make check` (ruff, mypy, pytest, hook tests, frontend typecheck) · `make e2e` · `make openapi`
- Evals: `make eval-offline` (no-LLM baseline, free) · `make eval` and `make seed-live` (paid; settings make them ask first)
- Add new workflows as Makefile targets instead of one-off command lines.
---- AI design rules (product code)
1. The model judges, code decides. Models return labels, extracted fields, ratings and rationales; thresholds, routing, scores and permissions are deterministic code and config.
2. AI never blocks a submission. A submission is saved before any model call, enrichment runs in the background, and if the provider fails or refuses, the request goes to the PM triage queue (status needs_review, with a reason). Above the calibrated threshold a duplicate link is applied automatically (status auto_linked), shown to the PM and undoable; below it, the link is only a suggestion.
3. User text is untrusted data. Pass it inside XML tags, never as instructions, and give the model no tools that write in the intake path. A successful prompt injection can at worst produce a wrong suggestion that a human reviews or undoes.
4. Structured outputs only, validated with Pydantic. No regex parsing of model prose.
5. Every model call goes through the gateway and is recorded in ai_runs (step, model, prompt version, tokens, cost, latency, outcome).
6. Every AI action is reversible (link and unlink, never delete), and every AI-generated value in the UI shows its source, confidence and rationale.
7. An LLM step must beat the no-LLM baseline on the evals to earn its cost. A prompt or model change bumps the prompt version and requires an eval run recorded in evals/REPORT.md.
8. Tests never call a real model: use FakeLLM. AI_MODE defaults to offline; live calls follow the limits under Never.
9. Redact emails and phone numbers before text goes to a provider. Never log secrets.

---How to work
- When I ask for options, compare two or three against the assignment's criteria (business value, AI fit, production readiness, time), recommend one, and say what would change your mind.
- For changes touching more than two files, give a short plan (files, approach, risks) before editing, then continue. Stop and ask only for a decision that changes the product or spends money.
- Test-first for deterministic logic: write the failing test, run it and show it fail, then implement (`tdd` skill). Eval cases come before the prompt that has to pass them.
- Done means: `make check` passes, tests cover the new behavior, docs/ADRs and docs/requirements.md are updated, and the prompts.txt entry is written. For a docs-only prompt, skip `make check` and the reviewer. If something isn't verified, say so.
- Never weaken, skip or delete a test to make it pass, and never mock the unit under test.
- When a requirement is ambiguous, choose the simplest reasonable option, note it under "Assumptions" in docs/spec.md, and keep going.
- Record significant decisions as ADRs: docs/adr/NNNN-title.md with context, decision, alternatives rejected, consequences.
- Before calling a feature done, run the `reviewer` subagent on the diff and address its findings.
- Commit after each completed prompt with a Conventional Commits message, without waiting for my ok, and keep Claude's Co-Authored-By line: this project shows AI-assisted work, so this overrides my global rules. Push after each commit (git push asks me first).

--- Never
- Read or print .env or any secret.
- Add a dependency without saying why in the summary.
- Call a model provider outside app/ai/gateway.py, or persist model output without validating it in code.
- Make a live model call any way other than `make eval` or `make seed-live`, which ask me first. Any other live use (one-off calls, `make dev` or `make e2e` with AI_MODE=live) needs the call count, expected cost and my go.
