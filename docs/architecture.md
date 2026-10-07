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
    Services["app/services<br/>requests, needs, triage, metrics"]
    Worker["worker loop<br/>(started in lifespan)"]
    Pipeline["app/ai/pipeline.py<br/>redact, embed, retrieve, extract,<br/>adjudicate, route, enrich, score"]
    Scoring["app/scoring.py<br/>routing and priority math"]
    Gateway["app/ai/gateway.py<br/>the only provider caller;<br/>writes ai_runs"]
    Embedder["Embedder<br/>fastembed bge-small (local)"]
  end
  DB[("SQLite (WAL)<br/>tables, job queue,<br/>event log, vectors")]
  Config["config/*.yaml<br/>routing, priorities, goals"]
  Anthropic["Anthropic API<br/>(AI_MODE=live)"]
  Offline["Offline provider<br/>heuristics and baseline<br/>(AI_MODE=offline, default)"]
  Evals["evals/ runner<br/>same pipeline and gateway"]

  SPA -->|HTTP/JSON| Routes --> Services --> DB
  Services -->|"suggest (no LLM)"| Embedder
  Worker -->|claim job| DB
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
- **Gateway.** It exposes `extract`, `adjudicate`, `rate_fit`, `brief` and `agent_step`. It redacts emails and phone numbers in every input, including agent tool results, before any provider call (rule 9). Providers are AnthropicProvider, OfflineProvider, and FakeLLM in tests (ADR 0006). Prompts live in `app/ai/prompts/<step>_v<N>.md`.
- **Vectors.** They are float32 BLOBs in the `embedding` table, loaded into one numpy matrix at startup and updated on write. Search is brute-force cosine (ADR 0005).

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
  UI->>API: GET /needs/suggest?q=... (debounced)
  API->>API: embed + numpy search (no LLM, under 300 ms)
  API-->>UI: top 5 needs (problem plus persona)
  alt "This is my need"
    R->>UI: claim need N, with why and severity
    UI->>API: POST /requests {claimed_need_id: N}
  else New request
    UI->>API: POST /requests
  end
  API->>DB: one transaction: request(pending, redacted_text) + claimed link(active)? + support? + job(queued) + event
  API-->>UI: 201 (saved before any model call)
  W->>DB: claim the oldest queued job (state=running, attempts+1)
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
    W->>DB: one transaction: extraction, links, request status, events, job done
  else transient error, attempts < N
    W->>DB: job queued again, available_at = now + backoff, last_error
  else refusal, second max_tokens or validation failure, or attempts = N
    W->>DB: request needs_review (reason), active claim disputed, job failed, event
  end
  Note over W,DB: On startup, running jobs older than the lease go back to queued.
```

## Decision brief with the overlap agent (should)

```mermaid
flowchart TD
  A["PM: Generate brief for need N"] --> B["job(kind=brief) queued"]
  B --> C["Gather facts in code:<br/>need, requests, supports, accounts,<br/>D/U/S components, goals"]
  C --> D{"Overlap agent enabled?"}
  D -- yes --> E["Agent loop (gateway.agent_step)<br/>read-only tools: search_needs, get_need, list_requests<br/>step cap 8, no write tools"]
  E --> F["Verify findings in code:<br/>need ids exist, quotes found verbatim"]
  F --> G
  D -- "no (time cut)" --> G["One LLM call (gateway.brief)<br/>facts and findings inside XML tags,<br/>structured claims with source id, quote, number"]
  G --> H["Verify in code:<br/>each quote is in its cited source,<br/>each number equals a value in the facts table"]
  H --> I["Store brief: verified claims shown,<br/>unverified claims flagged, ai_run ids"]
  I --> J["PM reads it; status decisions stay human"]
```

The brief is a workflow, because its inputs are known in advance. The agent is the only step whose path isn't known ahead of time: which needs to search for depends on what it finds. That is why it is the only agent (ADR 0001).
