# 0002. Two-stage dedupe: retrieval for recall, the LLM for precision

Status: accepted, 2026-10-07

## Context
Duplicates hinge on meaning, not words. One solution can serve two needs (Excel export for finance vs for IT), and three solutions can serve one need (email report, weekly PDF, Slack digest). The typing suggestions must answer in under 300 ms, so they can't use an LLM. Sending the whole backlog to an LLM on every request grows with the backlog and can't power the typing path.

## Decision
- **Stage 1 (recall).** Local fastembed `bge-small`, behind an `Embedder` interface, embeds every request plus one canonical problem-plus-persona text per need. Retrieval scores each need by its best-matching vector and returns the top 5 needs. The same vectors serve three uses: the typing suggestions, intake retrieval, and the no-LLM baseline.
- **Stage 2 (precision).** The LLM adjudicates only those 5 candidates (same_need, related or different, with a rationale and quotes), and code routes (ADR 0003).
- **Recall is its own metric.** Retrieval recall@5 is measured separately, because a candidate stage 1 misses can never be recovered by stage 2. If recall@5 on the paraphrase cases falls below 90%, we switch the Embedder to Voyage AI.
- `make setup` downloads the model, so offline mode works without a network.

## Alternatives rejected
- **Voyage AI from the start.** Likely better recall, but it adds a second vendor and key, adds 100-300 ms of network time to the typing path, and still needs an offline fallback. It stays the planned switch, not the default.
- **No embeddings (the LLM reads the backlog).** It can't power the typing suggestions, and its cost and latency grow with the backlog.
- **Indexing needs only (an averaged or canonical vector per need).** An average of three phrasings lands between them and matches none well, and the canonical text is LLM-written and changes when rewritten. Indexing individual requests keeps the users' own words and makes merge and unmerge simple relinks. The canonical vector is added on top, so a need with one request still has a clean description.

## Consequences
- Adds dependencies: fastembed, onnxruntime and numpy (justified here; listed in the summary when they are added).
- Changing the embedding model means re-embedding everything. `embedding.model` and `text_hash` make that detectable.
- Stage 2's precision depends on stage 1's recall, so both are reported in evals/REPORT.md.
