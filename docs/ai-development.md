# How Distill was built with AI

Distill was built in one day with Claude Code (Opus) as the main agent, a reviewer subagent, and two Sonnet subagents for the UI. Robert directed it prompt by prompt, made the product decisions and checked the evidence. Every prompt is in [prompts.txt](../prompts.txt), and the raw audit trail is in `prompts.audit.jsonl`. This page summarizes how the work was kept honest; the git history has the detail.

## The harness: guidance plus guarantees

[CLAUDE.md](../CLAUDE.md) is guidance. It says how to work: test-first, eval-first, the AI design rules, done means `make check`, a reviewer before "done", and commits in Conventional Commits. Guidance can be skipped, though, and some rules mattered too much for that. Those became **hooks** (`.claude/hooks/`, 29 tests in `make check-hooks`), which Claude Code runs whether or not the model remembers:

| Hook | When | What it guarantees |
|---|---|---|
| `log_prompt.py` | Every prompt (UserPromptSubmit) | The raw prompt is appended to `prompts.audit.jsonl`, with API keys and tokens redacted first. |
| `guard_prompt_log.py` | Before every edit or shell command | Nothing rewrites `prompts.txt` or the audit file. It includes a small shell lexer, so `>` redirects, `sed -i` and heredocs are caught too. |
| `require_prompt_log.py` | When a turn ends (Stop) | A turn that ends without its `prompts.txt` entry is sent back once to write it. |
| `format_python.py` | After every Python edit | ruff formats the file, so style never reaches review. |

Around the hooks:
- **Permissions** (`.claude/settings.json`). Paid commands (`make eval`, `make seed-live`) and `git push` ask first. Reading `.env` and force pushes are denied.
- **Path-scoped rules** (`.claude/rules/`). They load only when touching AI code, tests or the frontend.
- **The `reviewer` subagent** (Opus, read-only Bash). It ran on the diff before each feature was called done, with one exception: the gap fixes in #21 (provider-failure spec, stuck requests, code split) went in without a review.

## Test-first and eval-first

Deterministic logic was written test-first. The failing run was shown before the implementation, with stubs in place so tests fail on assertions rather than imports. The exceptions are recorded too:
- the 8 seed data checks in #9 passed on their first run, because the data was written first;
- two Playwright specs were written after the code they test: GP5 (stakeholder updates, #19) and GP6 (provider failure, #21). GP7 ("Brief me", #25) was written first, like GP1-GP4.

Real examples from the log:

| Step (prompt) | Red | Green |
|---|---|---|
| API contract (#9) | 31 contract tests, all 404 or missing keys | Domain model, routes and error shape |
| Eval metrics (#10-#11) | 11 metric tests raising NotImplementedError | Wilson intervals, precision and recall, false-merge rates |
| AI layer (#12) | 63 tests: gateway, pipeline, worker, policy | The intake workflow; 25 more red tests after the review |
| Cost bug (#13) | 2 tests: a dated model id priced at $0 | Pricing by the configured model; unpriced models refused |
| Priority score (#16) | 27 of 37 scoring tests, red on assertions against a stub | `app/scoring.py`; one test-data error fixed before green |
| Commitment check (#19) | 12 tests, then 17 more from the review (curly apostrophes, "in two weeks", 24/7) | `app/ai/commitments.py` |
| Hardening (#20) | 10 tests, then a regression test for `/needs/+1/support` | Route-matched rate limits, body caps, request IDs |
| Decision briefs (#25) | 40 tests (25 brief, 9 gateway and client, 6 API) red on stub output, with FakeLLM scripted to make tool calls; GP7 red (no button); then 15 more red tests from the review | `app/ai/brief.py`, the gateway's agent turn and brief call, the job and the panel; two test bugs fixed and explained |

**AI behaviour was eval-first, with three exceptions listed below.**
- **Hard cases came before the prompt that had to pass them.** Robert wrote the 17 hard cases (`evals/datasets/test_handwritten.jsonl`) before any prompt existed.
- **The test set was frozen before any tuning.** See commit `3ce8b0d` "test(evals): freeze the test set before any tuning". The runner refuses to run if its SHA-256 changes.
- **The no-LLM baseline was measured first.** The models had to beat it.
- **The strategic-fit eval waits for a human.** Its 11 cases are written, and the paid run refuses to start until a human has labelled every case.

Three exceptions:
- `strategic_fit_v1.md` and its cases landed in the same commit (`5938328`), so the history can't show which came first;
- `stakeholder_update_v1` has no eval at all; its safety net is the deterministic commitment check plus a PM approving every message (requirements D8 for the feature, D10 for the eval gap);
- extraction has no eval of its own; it is measured only through the routing decisions it feeds;
- the brief's two prompts (`related_needs_v1`, `decision_brief_v1`, #25) have no eval yet. Their deterministic checks were written test-first, and the comparison an eval would need to beat (the nearest-need baseline, the template brief) is in the code (ADR 0012).

## How the evals changed the decisions

- **Haiku over Sonnet.** The plan assumed Sonnet 5.5 as the reference model. On dev the two overlapped, so the simpler and cheaper Haiku won, and the frozen test set confirmed it: 91.3% against 74.7%. The surprise was that Sonnet with this prompt didn't beat the no-LLM baseline on accuracy (74.7% against 71.3%). It never false-merged, but it labelled true duplicates `related` whenever the requester's persona differed from the need's ([REPORT §3](../evals/REPORT.md)).
- **The cascade was dropped.** A cascade (Haiku first, Sonnet for the gray zone) was in the design. The eval showed that on exactly that band Sonnet was the weaker judge (72% against 96% on dev), and that the cascade lost to Haiku alone. It was never built.
- **The threshold was reported honestly.** The tuning rule picked T_auto = 0.6953, which turned out to equal Haiku's lowest same_need score on dev. The rule never bound, so in practice every same_need label auto-links. The docs say so, and the protection was moved to the audit sample and undo rather than claimed for the score.
- **A prompt change waits for its eval.** The persona failure (11 of Haiku's 13 test misses) produced an `adjudicate_v2` proposal with ship criteria. It isn't shipped, because it hasn't been evaluated.

## What Robert decided

The AI proposed, compared options and showed evidence; these calls were Robert's:
- **The hard cases.** The 17 hand-written eval cases.
- **The label reviews.** Keeping the two disputed test labels (T050, T065) as frozen, recorded as disputed rather than edited.
- **The thresholds.** Locking T_auto at 0.6953, stored unrounded, with the 10% audit sample kept on; keeping the routing score's placeholder weights.
- **The strategy.** Haiku 4.5 for both steps; no cascade; prompts stay at v1.
- **The human-in-the-loop policy.** What is automatic, suggested, or human-only ([spec §7](spec.md#7-human-in-the-loop-policy)).
- **The goals and weights.** Enterprise readiness 0.40, retention 0.35 and self-serve growth 0.25; the score weights 0.4, 0.4 and 0.2.
- **The commitment rule.** Flag timing and promises "unless the PM entered a date".
- **The process.** The CLAUDE.md rules, the permission scope, and every paid run's go.

One scope call was first made by omission. ADR 0001 planned to drop the related-needs agent if time ran short and keep the decision brief (F6), and Robert's rule was the same: "the agent goes and the brief stays". The first pass built neither, because the session moved on to the UI and hardening, not by an explicit decision. Robert then asked for both (#25): the brief as a workflow and the agent as the one bounded, read-only, verified loop. He leaned towards a manual loop on the plain SDK, and the comparison in [ADR 0012](adr/0012-decision-briefs-bounded-agent-manual-loop.md) agreed.

## Where the AI got it wrong

Each case comes from the log: what Claude did, how it was caught, and what changed.

| What Claude did | How it was caught | What changed |
|---|---|---|
| Used the SDK's `messages.parse`, which turns refusals and max-token stops into validation errors and drops their token counts | Reviewer subagent (#12) | The gateway calls `messages.create`, checks the stop reason first, then validates in code ([ADR 0008](adr/0008-model-boundary-details.md)) |
| Built a dev replay that showed the adjudicator example titles including the item's own title: a label leak | Reviewer subagent (#14) | Examples are snapshotted per item; dev was re-run (126 calls, $0.91); the report says so |
| Recorded Haiku calls at $0, because the API returned a dated model id missing from the price table | Checking the cost of the first live run (#13) | Pricing by the configured model; unpriced models are refused before the call |
| Ran the paid LLM eval directly instead of through `make eval` (it happened to hit the cache, so no calls were made) | Noticed in the session, and the reviewer flagged that the guard against paid calls was only an instruction (#14) | The runner refuses paid calls unless `make eval` sets `EVAL_ALLOW_PAID=1` |
| In the hardening step, added a rate limit that `/needs/+1/support` bypassed, and log redaction that a long URL could make quadratic | Security review by the reviewer subagent (#20) | The limit applies to the matched route plus a write budget by method; the email regex is linear; regression tests |
| Counted informational "related" suggestions as waiting for a PM, so M1 understated how many requests no PM had to touch | Checking the metrics after the e2e flow, before reporting them (#19) | A failing test, then the fix |
| Labelled AI-created needs "Created by PM" on the requester page (a subagent's page) | The consistency pass across both UI halves (#18) | One shared component for both need pages |
| Bound the web app to `localhost`, which is IPv6-only on the Linux CI runner, so Playwright never found it | The first CI run on GitHub (#22) | An explicit 127.0.0.1 bind, and server logs piped into CI |
| Wrote the live-brief script with `load_seed(engine)`, which loads the raw seed: 62 pending requests the live worker would have sent through the pipeline (about 124 paid calls) before the brief | Claude checked the queue in a scratch database before spending (#25) | The snapshot seed, and a guard that refuses to run while any other job is queued |
| Ran offline Playwright runs after each live golden-path run. They share and reseed `backend/data/e2e.db`, so both live runs' `ai_runs` rows were erased: the first run's by the offline runs between the two live runs, and the final run's rows behind REPORT §6 by the offline `make e2e` after it. A copy taken right after the final run missed the WAL file and was empty | Reviewer subagent, checking the report's numbers against the data (#27) | `make e2e-live` now has its own database; REPORT §6 states that its golden-path figures come from the queries made at the time and can't be re-derived |
| Wrote "settings ask first" on the two new paid Makefile targets, which wasn't true: `Bash(make *)` is allowed and only `make eval` and `make seed-live` ask | Reviewer subagent (#27) | The comments say the targets need Robert's go; an ask rule is proposed to Robert, not applied (`.claude/` changes are his) |
| Shipped the first brief build with 8 should-fix issues, among them: a tool exception that lost the brief; JSON-escaped tool results that made correct accented quotes fail; a 30 s timeout that a long Sonnet brief would hit; a failed repair call that threw away a usable brief; a call list that hid retries | Reviewer subagent (#25) | All fixed test-first, 15 new tests |

## The last prompts: decision briefs and the live validation (#24-#27)

- **The loop choice (#25).** Robert asked for the agent options to be compared before building. A manual loop on the plain SDK won on control (every turn goes through the gateway), testability (FakeLLM scripted with tool calls at our seam) and hosting (our process). Robert's lean was the same. ADR 0012 has the table.
- **Bounds first, as tests.** The 8-call cap, read-only tools, cited verbatim findings, money only from the data, one repair round and the brief surviving the agent were each a failing test before any loop code existed.
- **One live brief (Robert's go).** The SSO brief: 5 of 8 tool calls in 3 Haiku turns, one Sonnet call, 0 of 28 claims flagged, $0.0427 ([example](examples/brief-sso.md)). The cache write (2,621 tokens) shows the system prompt is above Sonnet's minimum. No cache read was shown, because there was only one call.
- **The live validation (asked in #24, run under #27, Robert's go in both).** The first live run of the golden paths passed 5 of 7. Neither failure was a product bug:
  - GP3's "gray zone" text is gray only for the embedding baseline, and Haiku correctly auto-linked it;
  - GP2 expected the offline label.

  The specs became mode-aware, and AI Ops gained the token columns it lacked. The final run passed 7 of 7 with 14 calls for $0.0688. The whole validation cost $0.1827 ([REPORT §6](../evals/REPORT.md#6-live-validation-2026-10-07-not-an-eval)).
- **What stayed human.** The go for every paid run, the loop lean, and the push of the docs commit (declined once, then pushed with the feature).
