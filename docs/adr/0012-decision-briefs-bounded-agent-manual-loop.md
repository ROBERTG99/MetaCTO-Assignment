# 0012. Decision briefs: a workflow with one bounded agent, on a manual tool loop

Status: accepted, 2026-10-07. Builds what ADR 0001 planned (spec F6).

## Context
The brief asks for "real-world agentic systems", and part of that is knowing when not to use an agent. A decision brief's inputs are known in advance: the need, its requests, its accounts, its scores, the goals. So the brief itself is a workflow: gather in code, one call, verify in code. One part has a path that isn't known in advance: finding what else in the backlog this need overlaps with, blocks or depends on. Which need to read next depends on what the last search returned. That is the one job given to an agent, and it has to be bounded, read-only and verifiable.

Four ways to run the agent loop were compared, on control over approvals and logging, testability with FakeLLM, and hosting:

| Option | Control and logging | Testable with FakeLLM | Hosting |
|---|---|---|---|
| **Manual loop on the plain SDK** | Every turn goes through the gateway: an `ai_runs` row, redaction, refusal and max_tokens mapping. The cap, the rejection of unknown tools and per-tool timing sit in about 60 lines we own. | Yes. FakeLLM replaces the client at our `LLMClient` seam and is scripted with tool calls. | Our process, our database |
| SDK tool runner (`client.beta.messages.tool_runner`) | Good per-turn hooks, but the turn boundary sits inside a beta helper, so per-turn bookkeeping has to be re-attached through hooks. | Only by faking HTTP, below our seam | Our process |
| Claude Agent SDK | A Claude Code harness with file and bash tools that would have to be switched off; a separate permission model | No | A subprocess harness |
| Managed Agents | Anthropic runs the loop and hosts a sandbox we don't need; every tool call comes back to us anyway, because the tools read our database | No | Anthropic-hosted session and sandbox |

## Decision
- **A manual loop on the plain SDK** (`app/ai/brief.py:run_agent`). Each turn is `Gateway.related_needs_turn`, which calls `AnthropicClient.converse` (`messages.create` with tools). Tool calling is a separate `ToolClient` protocol, so the eval replay clients don't have to implement it.
- **Bounded.**
  - At most 8 tool calls per run. Once the cap is reached, the next turn is sent with `tool_choice: none` and a note to answer with what it found. The result is flagged `incomplete`. Calls beyond the cap within one turn are answered "not run".
  - A 90-second wall-clock limit, checked before each turn.
  - `tool_choice` stays `auto`, because forcing a tool is a 400 on current models.
- **Read-only.**
  - Three strict tools (`search_needs`, `get_need`, `get_trend`). Their schemas forbid extra properties.
  - Any other tool name is rejected unrun, with an error result that names the allowed tools.
  - Bad arguments, or a tool that raises, are an error result, not a crash.
  - Nothing the agent can call writes.
  - Tool results carry backlog text, so the gateway redacts and escapes them like any other input.
- **Verifiable.**
  - **Findings.** Every finding cites a request and a quote. Code checks that the need exists, is live and isn't the need itself; that the request belongs to that need; and that the quote is in it verbatim. Failing findings are shown flagged in "How this brief was built" and never reach the brief.
  - **Brief.** The brief (`decision_brief_v1`, SMART_MODEL at medium effort) gets figures only as keyed facts computed in code. Code then checks:
    - every evidence quote is in its request verbatim;
    - every fact key exists;
    - every money figure typed in the prose equals a fact (within 5% when abbreviated, as in "$520k");
    - every related need is a verified finding.
  - **Repair and flags.** One repair round names the failing claims. The version with fewer failing claims is kept, and if the repair call itself fails the first brief is kept, flagged. Whatever still fails is shown flagged, and an invented figure is replaced with "[figure removed: not in the data]" in the prose and in any quote that failed its check, so it never reaches the PM. A verified quote is the requester's own text and is shown as written.
- **The brief survives the agent.** If the agent fails, is refused or times out, the brief is still written. The brief model is told related needs weren't checked, and the brief says so.
- **A job, not a request.** The `Brief` row is its own job (the ADR 0007 pattern), with at most one waiting per need (a partial unique index):
  - `POST /needs/{id}/brief` returns 202, and a brief already waiting is returned instead of a second one.
  - The worker builds it under the request ID `brief-<id>`, retries transient errors, and reclaims rows left in `processing` at startup (a 1-hour lease otherwise).
  - "How this brief was built" lists every `ai_runs` row with that request ID: retries, repair rounds and failed attempts included.
  - While a new brief builds or after it fails, the last ready brief stays visible.
  - The trajectory (tool, arguments, result size, latency, the turn's `ai_run`) is stored with the brief.
- **Models and caching.**
  - The agent runs on FAST_MODEL (Haiku 4.5): it navigates search results, and what matters is checked in code.
  - The brief runs on SMART_MODEL (Sonnet 5.5), the only step that writes judgment for a reader, with its own 180-second timeout (up to 12k output tokens at about 90 tokens a second).
  - Agent turns get one max_tokens retry at double the limit, like every other step.
  - At most 25 requests are quoted to the brief, blockers and the biggest accounts first; counts and money cover all of them.
  - The brief's system prompt is static and above Sonnet 5.5's minimum cacheable prefix, so it is marked for caching (`StepConfig.cache`).
  - The agent's prefix (about 370 tokens of system prompt plus three tools) is far below Haiku 4.5's 4,096-token minimum, so it isn't cached.
  - Cache writes are costed at 1.25x and reads at 0.1x the input price, and both are recorded in `ai_runs`.
- **Offline mode is a baseline, labelled as one.**
  - The agent step searches once with the need's text, reads the nearest need above a 0.5 similarity floor, and reports it as an overlap.
  - The brief is a template of the facts and verbatim quotes, with no recommendation and confidence 0.
  - The e2e spec (GP7) runs this path without a network.

## Alternatives rejected
- **An agent for the whole brief.** Its inputs are known in advance. A loop would add turns, cost and variance without finding anything the code can't gather.
- **Letting the model type figures and checking them afterwards only.** The brief cites fact keys, and the UI shows the cited values next to each impact claim. Checking typed figures stays as the second line of defence.
- **Dropping failing claims silently.** A PM can't tell a missing claim from one that was never made. Flags keep the model's output visible and mark what didn't hold.
- **A synchronous endpoint.** A live brief takes about 40 seconds (three agent turns and a 21-second brief call in the live run). The job pattern keeps the API responsive and makes the brief durable across restarts.

## Consequences
- **The live SSO brief** ([docs/examples/brief-sso.md](../examples/brief-sso.md), `make brief-live`):
  - **Agent:** 5 of 8 tool calls in 3 Haiku turns (it made parallel calls). It found that SCIM provisioning depends on SSO, plus two Google-login needs that overlap.
  - **Brief:** one Sonnet call, 0 of 28 claims flagged, no repair round.
  - **Cost and latency:** $0.0427 for 4 calls in about 37 seconds.
  - **Cache:** the brief call wrote 2,621 tokens to the cache (the system prompt and the output schema). It read 0, because the cache only pays off on a second brief within 5 minutes.
  - It was generated before the reviewer's fixes (tool errors, unescaped JSON in tool results, the request cap, the repair fallback, trace-based call listing, the brief timeout). None of them changes how this brief was verified: it had 5 requests, no non-ASCII quotes and no failing claims.
- **No eval yet for `related_needs_v1` or `decision_brief_v1`** (CLAUDE.md rule 7 is not met). The comparison an eval would need to beat is the offline baseline: the nearest need for the agent, the template for the brief. Until then, the safety net is the verification in code and a PM reading the brief.
- **What the checks don't cover:**
  - Counts in prose ("five accounts") aren't checked; only money is.
  - A finding is checked for its citation, not for whether the relation is right; the PM judges that.
- **Prompt injection through backlog text can at worst produce a wrong finding or a wrong framing** that a PM reads, because the agent can only read.

