# Architecture

Product behavior: [spec.md](spec.md). Decisions: [adr/](adr/). Paths follow the architecture map in CLAUDE.md. `config/` sits at the repo root, so the backend and the evals read the same thresholds and weights.

## Components

```mermaid
flowchart LR
  subgraph Browser
    SPA["React SPA<br/>(Vite, TanStack Query,<br/>types generated from OpenAPI)"]
  end
  subgraph API["FastAPI process"]
    Routes["app/api<br/>thin routes"]
    Services["app/services<br/>requests, needs, triage, priority,<br/>updates, briefs, portal, metrics"]
    Worker["worker loop<br/>(started in lifespan)"]
    Pipeline["app/ai/pipeline.py<br/>redact, embed, retrieve, extract,<br/>adjudicate, route, enrich, score"]
    Scoring["app/scoring.py<br/>routing and priority math"]
    Gateway["app/ai/gateway.py<br/>the only provider caller;<br/>writes ai_runs"]
    Embedder["Embedder<br/>fastembed bge-small (local)"]
  end
  DB[("SQLite (WAL)<br/>tables, request queue,<br/>link history")]
  Config["config/*.yaml<br/>routing, priorities, goals"]
  Anthropic["Anthropic API<br/>(AI_MODE=live)"]
  Offline["OfflineClient<br/>heuristics and baseline<br/>(AI_MODE=offline, default)"]
  Evals["evals/ runner<br/>same pipeline and gateway"]

  SPA -->|HTTP/JSON| Routes --> Services --> DB
  Services -->|"suggest (no LLM)"| Embedder
  Worker -->|claim pending row| DB
  Worker --> Pipeline
  Pipeline --> Embedder
  Pipeline --> Scoring
  Pipeline --> Gateway
  Scoring --> Config
  Gateway --> Anthropic
  Gateway --> Offline
  Gateway -->|ai_runs| DB
  Evals --> Pipeline
```

- **One process.** The API, the worker loop and SQLite all run in one process (ADR 0005, ADR 0007). The worker code doesn't depend on the web layer, so it can later run as its own process.
- **Gateway.** It exposes one method per model step: `extract`, `adjudicate`, `rate_fit` and `draft_updates`. It redacts emails and phone numbers in every input before any provider call (rule 9). Clients are `AnthropicClient`, `OfflineClient` (heuristics, the baseline, template drafts), `FakeLLM` in tests and `FaultInjectingClient` (only with `APP_ENV=test`, for the e2e failure path) (ADR 0006, ADR 0008). Prompts live in `app/ai/prompts/<step>_v<N>.md`.
- **Vectors.** They aren't stored: at startup the index embeds every member request and need with the local model into one numpy matrix, and updates it on write. Search is brute-force cosine (ADR 0005).

## Intake sequence (through the database queue)

```mermaid
sequenceDiagram
  actor R as Requester
  participant UI as SPA
  participant API as FastAPI
  participant DB as SQLite
  participant W as Worker loop
  participant P as Pipeline
  participant G as Gateway
  participant M as Model provider

  R->>UI: types title and description
  UI->>API: GET /needs/similar?q=... (debounced)
  API->>API: embed + numpy search (no LLM, under 300 ms)
  API-->>UI: top 5 needs (problem plus persona)
  alt "This is my need"
    R->>UI: claim need N, with why and severity
    UI->>API: POST /needs/N/support
    API->>DB: support(claimed) + LinkEvent(link, requester_claim)
    API-->>UI: 201 (or 200 on a repeat); counted only once confirmed
  else New request
    UI->>API: POST /requests
    API->>DB: request(pending)
    API-->>UI: 201 (saved before any model call)
  end
  W->>DB: claim the oldest pending row (processing, attempts+1, claimed_at)
  W->>P: run(request)
  P->>P: embed redacted text, retrieve top 5 needs (+ the claimed need)
  P->>G: extract (text inside XML tags)
  G->>M: structured output call
  M-->>G: parsed result, or refusal / error
  Note over G: max_tokens or validation error: one retry inside the gateway
  G->>DB: ai_run (tokens, cost, latency, outcome)
  P->>G: adjudicate against candidates
  G->>M: structured output call
  G->>DB: ai_run
  P->>P: verify quotes, route (score vs thresholds), enrich, score
  alt success
    W->>DB: one transaction: AI fields, need_id, aisuggestion, LinkEvent, status processed
  else transient error, attempts < N
    W->>DB: back to pending with backoff, last_error
  else refusal, second max_tokens or validation failure, or attempts = N
    W->>DB: request needs_review (reason)
  end
  Note over W,DB: On startup, every processing row goes back to pending (lease 0: one process).
```

## Decision brief with the overlap agent

Built in #24 ([ADR 0012](adr/0012-decision-briefs-bounded-agent-manual-loop.md)); code in `app/ai/brief.py`, `app/services/briefs.py`.

```mermaid
flowchart TD
  A["PM: Brief me (POST /needs/N/brief)"] --> B["brief row queued (pending); 202"]
  B --> C["Worker: gather facts in code<br/>need, requests, accounts, ARR, pipeline,<br/>renewals, D/U/S, goals"]
  C --> E["Overlap agent: manual loop<br/>gateway.related_needs_turn per turn (Haiku)<br/>strict read-only tools: search_needs, get_need, get_trend<br/>cap 8 tool calls, 90 s; other tools rejected unrun"]
  E --> F["Verify findings in code:<br/>need live and not itself, request belongs to it,<br/>quote verbatim; failures flagged, not passed on"]
  E -- "fails or times out" --> G
  F --> G["One call: gateway.decision_brief (Sonnet, medium,<br/>cached system prompt); facts as keyed values,<br/>requests and verified findings inside XML tags"]
  G --> H["Verify in code: quotes verbatim, fact keys exist,<br/>money figures equal a fact, related needs verified"]
  H -- "a claim fails" --> R["One repair round naming the claims"] --> H2["Verify again; still failing: shown flagged,<br/>invented figures removed"]
  H --> I
  H2 --> I["Store: brief, facts, checks, trajectory, ai_run ids"]
  I --> J["PM reads it with How this brief was built;<br/>status decisions stay human"]
```

The brief is a workflow, because its inputs are known in advance. The agent is the only step whose path isn't known ahead of time: which need to read next depends on what the last search found. That is why it is the only agent (ADR 0001). Offline, the agent step is a labelled baseline (one search, the nearest need) and the brief a template of the facts and quotes.
