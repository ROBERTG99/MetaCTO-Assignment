# Distill

AI-first feature intelligence for a product team: unstructured feature requests in, deduplicated, need-centric and prioritized decisions out, with a PM in the loop. Built for the MetaCTO technical assessment ([docs/assignment.md](docs/assignment.md)). Work in progress: the backend, the AI layer, the requester portal and the PM workspace (triage, priorities, need detail, AI Ops) and stakeholder updates (AI drafts, a code commitment check, PM approval) exist and pass the golden-path specs.

- What and why: [docs/spec.md](docs/spec.md) · Architecture: [docs/architecture.md](docs/architecture.md) · Decisions: [docs/adr/](docs/adr/)
- Evals: [evals/REPORT.md](evals/REPORT.md) · Requirements traceability: [docs/requirements.md](docs/requirements.md)
- How AI was used to build it: [prompts.txt](prompts.txt) (every prompt, logged by hooks) and [CLAUDE.md](CLAUDE.md)

## Run it

```bash
make setup      # uv sync, the local embedding model (bge-small, 64 MB), npm ci and Playwright's Chromium
make seed       # reset the local SQLite DB to the Brightboard seed, with recorded Haiku 4.5 output (seed/snapshot.json)
make dev        # FastAPI on :8000 with its worker, and the web app on :5173 (AI_MODE=offline by default: no API key needed)
make check      # ruff, mypy, pytest, hook tests, frontend typecheck
make e2e        # Playwright golden paths against a fresh offline API (:8001) and web app (:5174)
```

`make seed` is real Haiku 4.5 output, replayed from the cached evals with no API calls: it splits 10 duplicates into needs of their own and links the vague "make it better" (R62) to an existing need, so the backlog has 27 needs where the ground truth has 17 (caveat in [evals/snapshot.py](evals/snapshot.py)). `make seed-raw` loads only the raw requests (no AI output). Evals: `make eval-offline` (free), `make eval-compare` (free, from cached replies), `make eval` and `make seed-live` (paid; they ask first). An API key goes in a repo-root `.env` (`ANTHROPIC_API_KEY=`), never in code or chat.

## The AI strategy, and what the threshold really is

Every request goes through an intake workflow: redact, embed, retrieve the 5 nearest needs, extract the underlying need, adjudicate against the candidates, then route in code. Both model steps run on **Haiku 4.5**: on the dev replay it overlaps Sonnet 5.5, so the simpler and cheaper model wins, and the frozen test set confirms it (91.3% vs 74.7%). Sonnet 5.5 with this prompt doesn't clearly beat the no-LLM baseline on accuracy (the intervals overlap), only on false merges. A stronger model wasn't automatically better ([REPORT §3](evals/REPORT.md)).

Routing uses a code-computed score, and a request auto-links at or above **T_auto = 0.6953**. To be plain about it:
- **The threshold is degenerate.** It equals the lowest score Haiku gives any same_need label on dev, so in practice *every same_need label auto-links*. The routing score doesn't separate Haiku's errors, and its weights are still placeholders.
- **The cost:** on test this means 3 false merges that no human reviews first, against 1 at 0.90. 0.90 would auto-link only 32% of true duplicates and send the rest to the PM, which defeats the point of the product.
- **The uncertainty:** the point estimate is 2.7%, inside the 3% target, but the 95% interval allows up to about 8%.
- **So the protection is the audit sample and undo, not the score.** 10% of auto-links go to the PM's Audit tab, which measures the real false-merge rate, and every link can be undone in one click.

## Limitations, and what would fix each one

| Limitation | Evidence | Fix |
|---|---|---|
| The data is synthetic: Brightboard, the seed and 133 of the 150 test cases were written by the team that built the system. | REPORT §1 | Real requests from a pilot, labelled by a PM who didn't build it. |
| Spanish (and any non-English) requests retrieve poorly: recall@1 is 1/4, because the embedding model, bge-small-en, is English-only. | REPORT §1, §3 | Evaluate a multilingual embedder (e.g. multilingual-e5-small in fastembed) on a Spanish slice of at least 20 cases, and switch if recall@5 holds. |
| Dev has no hard cases, so the threshold isn't stress-tested where it matters. The dev-tuned baseline failed on test exactly there. | REPORT §1, §3 | Write at least 25 hand-made hard cases for dev (same solution / different need, hard negatives), then choose T_auto again. |
| The adjudication prompt over-splits needs when the requester's persona differs from the need's: 11 of Haiku's 13 test misses. | REPORT §3, §4.4 | `adjudicate_v2` is proposed with ship criteria. It needs one eval run, about $0.80. |
| Two test labels are disputed (T050, T065). | REPORT §4.5 | A human decision, recorded as a new frozen test set (v2), never an edit of v1. |
