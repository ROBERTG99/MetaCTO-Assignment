# 0001. Workflow first, with one agent only where the path is open

Status: accepted, 2026-10-07. Outcome: the overlap agent was cut for time, as this ADR allowed. The decision brief it feeds (F6) wasn't built either, which goes beyond this plan (it said the brief stays). The product has no agent; every model step is a single call inside a code-orchestrated workflow.

## Context
The brief asks how we think about "real-world agentic systems". Anthropic's "Building effective agents" calls both workflows (predefined code paths around model calls) and agents (the model chooses its own steps and tools) agentic systems, and recommends the simplest one that works. Intake is the same eight steps for every request. A model choosing the path there would add cost, latency and variance, and would make each step impossible to evaluate on its own. The one open-ended question in the product is "what else in the backlog does this need overlap with, block or depend on?". Which needs to look at next depends on what the last search found.

## Decision
- Intake, routing, scoring, strategic fit and the decision brief are code-orchestrated workflows on the plain Anthropic SDK.
- The only agent is the overlap finder that feeds the brief (spec F6, should). It has read-only tools (`search_needs`, `get_need`, `list_requests`), a cap of 8 steps and no write tools, and it runs outside the intake path. Tool results come from redacted text and pass through the gateway's redaction like every other input. Its findings are verified in code before the brief cites them.
- If time runs short, the agent is cut and the brief stays.

## Alternatives rejected
- **LangGraph.** The flow is linear, and the human step happens after the run, through the database. Its real strength (pausing for a human mid-run and resuming) isn't needed here. We'd adopt it if a run ever has to wait for a human in the middle of many steps.
- **Agents everywhere (Claude Agent SDK or Managed Agents).** The Agent SDK is a Claude Code-style harness with file and bash tools. Managed Agents hosts a sandbox per session. Neither fits a web intake path. They would cost 5-20 turns per request instead of 2, change the path from run to run, and put tools that act in the intake path, which CLAUDE.md rule 3 forbids.

## Consequences
- Every step can be tested or evaluated in isolation, and cost is predictable: 2 calls per request.
- The Loom answer to Q5 is explicit: a workflow where the path is known, an agent only where it isn't.
- The agent needs its own controls: a step cap, a check that it stays read-only, and verification of what it finds.
