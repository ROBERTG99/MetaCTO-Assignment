# Eval report

Every model or prompt change adds a section here (CLAUDE.md rule 7). Numbers come from `evals/run.py` and `evals/results/*.json`. Rerun with `make eval-offline SPLIT=dev|test`; apart from latency, the results are deterministic.

## 1. Baseline without an LLM (2026-10-07)

**Code:** the commit "feat(evals): hard cases, frozen test set and no-LLM baseline". The test set was frozen earlier, in its own commit `3ce8b0d`. The result files and `config/routing.yaml` record `git: 3ce8b0d-dirty`: they were produced from the working tree that became this commit, which can't contain its own hash. Rerun to verify; apart from latency, the output is identical. **Embedding model:** `BAAI/bge-small-en-v1.5` (local, 384 dims, English only). **Thresholds:** `config/routing.yaml`, tuned on dev only and stored unrounded: auto ≥ 0.7666, suggest ≥ 0.6508.

> **The data is synthetic** (spec A1). Brightboard, its 62 seed requests, the ground truth and 133 of the 150 test cases were written by the author or by Claude. The 17 handwritten cases are Robert's. These numbers measure agreement with labels written by the same team that designed the system, not with real customers. Intervals are Wilson 95%.

> **The test split has now been seen.** These baseline test numbers are the confirmatory run. Any later change to the baseline thresholds is informed by them: it must be labelled "post hoc, test seen" here, or be confirmed on new held-out cases.

### Datasets

| Split | What | Size |
|---|---|---|
| dev | The seed stream replayed in arrival order. Each request is routed against the backlog built so far; right = linked to the right existing need, or "new" when its cluster first appears. After each decision the backlog takes the true label, so errors don't compound. The noise request becomes its own need, as a PM would create one. Tuning happens here only. | 62 decisions: 44 repeats, 18 first appearances (17 needs + 1 noise) |
| test | `evals/datasets/test.jsonl`, frozen (SHA-256 `8c52554c8497…` in `FROZEN`). Each case is routed against the curated backlog: 17 needs, their 61 labelled requests, and one canonical text per need (the noise request is not a need). | 150 cases: 17 handwritten (`reviewed_by_human: true`), 133 generated (`false`). Slices: 25 each of same-solution/different-need, different-solution/same-need, hard negative, paraphrase; 20 clear duplicates; 24 new needs; 2 prompt injections; 4 in Spanish. 25 cases expect "new": the 24 new-need cases plus one hard negative (BigQuery). |

### Retrieval recall (stage 1, ADR 0002)

| Split / slice | n | Recall@1 | Recall@3 | Recall@5 |
|---|---|---|---|---|
| dev (repeats) | 44 | 77.3% (34/44; 63-87%) | 90.9% (40/44; 79-96%) | 95.5% (42/44; 85-99%) |
| test (all with an existing need) | 125 | 80.8% (101/125; 73-87%) | 98.4% (123/125; 94-100%) | 100.0% (125/125; 97-100%) |
| test: paraphrase | 25 | 64.0% (16/25; 45-80%) | 96.0% (24/25; 80-99%) | 100.0% (25/25; 87-100%) |
| test: Spanish | 4 | 25.0% (1/4; 5-70%) | 100.0% (4/4; 51-100%) | 100.0% (4/4; 51-100%) |
| test: handwritten | 16 | 81.2% (13/16; 57-93%) | 100.0% (16/16; 81-100%) | 100.0% (16/16; 81-100%) |

**Gate: paraphrase recall@5 ≥ 90%.** It passes, so Voyage is not needed for now.
- With only 17 needs, the top 5 covers almost a third of the backlog, so recall@5 is an easy bar.
- Recall@1 (64% on paraphrases) is the honest measure of what the embeddings understand.
- The adjudicator should see all 5 candidates. Recall@3 is nearly complete on test, but dev misses 4 of 44 at k=3.

### Baseline decisions

#### dev: baseline (auto ≥ 0.7666, suggest ≥ 0.6508)

| Slice | n | Accuracy | False merges (all links) | False merges (auto) | Recall@1 | Recall@3 | Recall@5 | Bands auto/suggest/new |
|---|---|---|---|---|---|---|---|---|
| all | 62 | 62.9% (39/62, CI 50-74%) | 39.3% (22/56, CI 28-52%) | 0.0% (0/13, CI 0-23%) | 77.3% (34/44, CI 63-87%) | 90.9% (40/44, CI 79-96%) | 95.5% (42/44, CI 85-99%) | 13/43/6 |
| first_appearance | 18 | 27.8% (5/18, CI 12-51%) | 100.0% (13/13, CI 77-100%) | n/a (n=0) | n/a (n=0) | n/a (n=0) | n/a (n=0) | 0/13/5 |
| repeat | 44 | 77.3% (34/44, CI 63-87%) | 20.9% (9/43, CI 11-35%) | 0.0% (0/13, CI 0-23%) | 77.3% (34/44, CI 63-87%) | 90.9% (40/44, CI 79-96%) | 95.5% (42/44, CI 85-99%) | 13/30/1 |

Duplicates: precision 60.7% (34/56, CI 48-72%), recall 77.3% (34/44, CI 63-87%), F1 0.680. Latency per decision (embed + search): p50 9.4 ms, p95 16.0 ms.

Accuracy by similarity bucket: [0.0, 0.5) 100.0% (1/1, CI 21-100%), [0.5, 0.6) 100.0% (1/1, CI 21-100%), [0.6, 0.7) 40.9% (9/22, CI 23-61%), [0.7, 0.8) 68.8% (22/32, CI 51-82%), [0.8, 0.9) 100.0% (6/6, CI 61-100%)

#### test: baseline (auto ≥ 0.7666, suggest ≥ 0.6508)

| Slice | n | Accuracy | False merges (all links) | False merges (auto) | Recall@1 | Recall@3 | Recall@5 | Bands auto/suggest/new |
|---|---|---|---|---|---|---|---|---|
| all | 150 | 71.3% (107/150, CI 64-78%) | 28.4% (40/141, CI 22-36%) | 10.2% (6/59, CI 5-20%) | 80.8% (101/125, CI 73-87%) | 98.4% (123/125, CI 94-100%) | 100.0% (125/125, CI 97-100%) | 59/82/9 |
| clear_duplicate | 20 | 100.0% (20/20, CI 84-100%) | 0.0% (0/20, CI 0-16%) | 0.0% (0/17, CI 0-18%) | 100.0% (20/20, CI 84-100%) | 100.0% (20/20, CI 84-100%) | 100.0% (20/20, CI 84-100%) | 17/3/0 |
| different_solution_same_need | 25 | 92.0% (23/25, CI 75-98%) | 8.0% (2/25, CI 2-25%) | 0.0% (0/6, CI 0-39%) | 92.0% (23/25, CI 75-98%) | 100.0% (25/25, CI 87-100%) | 100.0% (25/25, CI 87-100%) | 6/19/0 |
| generated | 133 | 70.7% (94/133, CI 62-78%) | 29.0% (36/124, CI 22-38%) | 9.8% (5/51, CI 4-21%) | 80.7% (88/109, CI 72-87%) | 98.2% (107/109, CI 94-99%) | 100.0% (109/109, CI 97-100%) | 51/73/9 |
| handwritten | 17 | 76.5% (13/17, CI 53-90%) | 23.5% (4/17, CI 10-47%) | 12.5% (1/8, CI 2-47%) | 81.2% (13/16, CI 57-93%) | 100.0% (16/16, CI 81-100%) | 100.0% (16/16, CI 81-100%) | 8/9/0 |
| hard_negative | 25 | 68.0% (17/25, CI 48-83%) | 32.0% (8/25, CI 17-52%) | 20.0% (2/10, CI 6-51%) | 70.8% (17/24, CI 51-85%) | 95.8% (23/24, CI 80-99%) | 100.0% (24/24, CI 86-100%) | 10/15/0 |
| new_need | 24 | 25.0% (6/24, CI 12-45%) | 100.0% (18/18, CI 82-100%) | 100.0% (2/2, CI 34-100%) | n/a (n=0) | n/a (n=0) | n/a (n=0) | 2/16/6 |
| non_english | 4 | 25.0% (1/4, CI 5-70%) | 66.7% (2/3, CI 21-94%) | 0.0% (0/1, CI 0-79%) | 25.0% (1/4, CI 5-70%) | 100.0% (4/4, CI 51-100%) | 100.0% (4/4, CI 51-100%) | 1/2/1 |
| paraphrase | 25 | 64.0% (16/25, CI 45-80%) | 30.4% (7/23, CI 16-51%) | 0.0% (0/4, CI 0-49%) | 64.0% (16/25, CI 45-80%) | 96.0% (24/25, CI 80-99%) | 100.0% (25/25, CI 87-100%) | 4/19/2 |
| prompt_injection | 2 | 100.0% (2/2, CI 34-100%) | 0.0% (0/2, CI 0-66%) | 0.0% (0/1, CI 0-79%) | 100.0% (2/2, CI 34-100%) | 100.0% (2/2, CI 34-100%) | 100.0% (2/2, CI 34-100%) | 1/1/0 |
| same_solution_different_need | 25 | 88.0% (22/25, CI 70-96%) | 12.0% (3/25, CI 4-30%) | 11.1% (2/18, CI 3-33%) | 88.0% (22/25, CI 70-96%) | 100.0% (25/25, CI 87-100%) | 100.0% (25/25, CI 87-100%) | 18/7/0 |

Duplicates: precision 71.6% (101/141, CI 64-78%), recall 80.8% (101/125, CI 73-87%), F1 0.759. Latency per decision (embed + search): p50 6.0 ms, p95 7.8 ms.

Accuracy by similarity bucket: [0.5, 0.6) 0.0% (0/1, CI 0-79%), [0.6, 0.7) 60.7% (17/28, CI 42-76%), [0.7, 0.8) 67.8% (61/90, CI 58-77%), [0.8, 0.9) 93.3% (28/30, CI 79-98%), [0.9, 1.0] 100.0% (1/1, CI 21-100%)

"False merges (all links)" counts suggestions too, which a PM reviews before anything changes. "False merges (auto)" is what would change without a human.

### What the LLM strategies must beat

| Measure (test) | Baseline | Why it matters |
|---|---|---|
| Decision accuracy | 71.3% (107/150; 64-78%) | The headline. |
| Auto-link false merges | 10.2% (6/59; 5-20%) | The target is ≤ 3% (M4). The baseline misses it on test. |
| "New" kept new (all 25 cases that expect new) | 6/25 | The baseline can't say "this is new": similarity is always high to *something*. |
| New-need slice accuracy | 25.0% (6/24; 12-45%) | The same weakness, on the 24-case slice. |
| Gray-zone share (PM inbox) | 55% (82/150) | M1: the work left for the PM. |
| Paraphrase accuracy | 64.0% (16/25; 45-80%) | Same need, different words. |
| Hard negatives accuracy | 68.0% (17/25; 48-83%) | Related but different needs. |
| Handwritten cases accuracy | 76.5% (13/17; 53-90%) | Robert's own hard cases. |
| Latency per decision | p50 6.0 ms, p95 7.8 ms | An LLM adds seconds; that is acceptable in the background, not at the door. |

### Findings

1. **Dev-tuned auto-linking doesn't transfer to test.**
   - On dev the threshold gave 13 auto-links and 0 errors. On test it gave 59 auto-links, 6 of them wrong (10.2% (6/59; 5-20%)).
   - All 6 errors are in slices that dev doesn't contain: 2 hard negatives, 2 same-solution/different-need, 2 new needs. The main reason is that **dev has no hard cases.**
   - The canonical titles in the test backlog are not the cause. Without them, test gives 51 auto-links with 5 wrong (9.8%) and accuracy 102/150. The titles add about 8 links at the same error rate.
   - 13 error-free links on dev only bound the error rate at 0-25%, so the data was too thin to set a safe threshold anyway.
   - Fixing this means adding hard cases to dev. Re-tuning against test does not count (see the note above).
2. **The baseline has no notion of "new".** Only 6 of the 25 cases that expect a new need stayed new; the rest were linked or suggested to the nearest need. Judging "same problem or not" is where an LLM has to earn its cost.
3. **The baseline wins easy cases.** Clear duplicates score 100.0% (20/20; 84-100%). Same-solution/different-need does better than expected (88.0% (22/25; 70-96%)). One hypothesis, not tested: the generated cases reuse the seed's vocabulary, a known bias of synthetic data.
4. **Spanish is weak** (recall@1 25.0% (1/4; 5-70%)), as expected from an English-only model. The n is too small to conclude more.
5. **Prompt injection can't move the baseline.** No text is interpreted, so both injection cases routed on their real ask.
6. **A rounding bug was fixed before this report.** The first tuning rounded the thresholds to 3 decimals. That pushed the auto threshold past an observed boundary score, so the configured value didn't implement the rule (dev showed 12 auto-links instead of 13). Thresholds are now stored unrounded, with a test. This is a bug fix to the pre-declared rule, not a re-tune, and it doesn't change any test result.

## 2. Live smoke run, n = 3 (2026-10-07). Not an eval.

`make seed-live REFS=R22,R13,R07` ran three seed requests through the live pipeline against the curated backlog (the 17 seeded needs). Models: Haiku 4.5 for extraction, Sonnet 5.5 at its default effort for adjudication, with prompts `extract_need_v1` and `adjudicate_v1`. The run checks that the plumbing works end to end; three cases say nothing about quality. The LLM strategies are still to be evaluated on the frozen test set (`make eval`).

| Request | Truth | Outcome | Right? |
|---|---|---|---|
| R22: an IT admin's Excel/CSV export to migrate | data_portability | auto-linked to data_portability (routing score 0.95); excel_finance labelled related | yes |
| R13: a Slack digest of KPIs | share_kpis | suggested for share_kpis (0.896, just under auto at 0.90) | yes, routed to the PM |
| R07: Google login plus a prompt injection | sso | the injection was ignored and nothing auto-linked, but it became a **new need**; SSO was labelled related (end user vs IT admin persona) | no: over-split |

- **Cost:** 6 calls, all `ok`, **$0.036** in total. Extraction: 1,346-1,371 input and 193-295 output tokens, 4-9.5 s. Adjudication: 1,866-1,921 input and 516-617 output tokens, 5.5-6.3 s.
- **A bug the run exposed, fixed after it.** The API answered with the dated id `claude-haiku-4-5-20251001`, which the price table missed, so the Haiku calls were recorded at $0. The gateway now prices by the configured model and refuses an unpriced model (tests in `test_gateway.py`). The three rows in the local database still show $0 for Haiku; the figure above is recomputed from their tokens.
- **What to watch in the eval:** R07 suggests the persona rule in `adjudicate_v1` can split "the same problem, different requester" too eagerly. The same-solution and different-solution slices will show whether it costs recall.

## 3. Model strategy comparison (2026-10-07)

**Setup.** `make eval` ran on the frozen test set (SHA-256 `8c52554c…`) and the dev replay. Run metadata is in `evals/results/llm_run.json`.
- **Extraction:** Haiku 4.5 for every strategy. Each case is extracted once and shared, so the strategies differ only in the adjudicator.
- **Adjudicators:** `haiku` (Haiku 4.5), `sonnet` (Sonnet 5.5 at its default, high), `sonnet-low` (Sonnet 5.5 at effort low). Note: ADR 0006's C3 meant Sonnet-low for *both* steps; here it ran with Haiku extraction, as asked, so C3-as-defined was not measured.
- **`baseline`:** embeddings and thresholds only (§1), recomputed per case.
- **Routing:** the app's own code (`app/ai/policy.py`, `pipeline._score`) with `config/routing.yaml` unchanged: T_auto 0.90, T_suggest 0.60, and s_min/s_max and weights that are still placeholders. Prompts `extract_need_v1` and `adjudicate_v1`.
- **Dev replay:** a need is born from the Haiku extraction of its first request. Each decision sees only the backlog that existed when it arrived.
- **Spend:** 971 calls, **$5.88** in total. 845 calls ($4.97) were the first run. A reviewer then found that the first dev replay leaked labels: the example titles shown to the adjudicator included the item's own title and later ones. Fixing it re-ran 126 dev adjudications ($0.91); test was unaffected. 0 failures.
- **Reproducing it:** every reply is cached in `evals/results/llm_cache.jsonl`, and `make eval-compare` rebuilds the tables for free.

**How to read the tables.** Each cell is the value (k/n; 95% Wilson interval).
- **Accuracy:** a decision is right if it links to the expected need, or keeps a new request new. A provider failure counts as wrong but never as a link.
- **False merges:** "(links)" counts suggestions too, which a PM reviews; "(auto)" counts only what changes without a human.
- **Latency:** per request (extraction plus adjudication), measured with 8 calls in parallel, one strategy at a time, including SDK retries. It is not representative of a single request, and differences of about 1 s between strategies are confounded with time of run. Per call p50: extraction 4.2 s; adjudication 6.1 s (Haiku), 5.2 s (Sonnet), 4.8 s (Sonnet low).
- **Cost:** per request, both calls.
- **Baseline latency:** re-measured on each `make eval-compare`, so only those cells drift.

**dev (n = 62)**

| Strategy | n | Accuracy | Dup precision | Dup recall | F1 | False merges (links) | False merges (auto) | auto/suggest/new/failed | p50 / p95 latency | $ / request |
|---|---|---|---|---|---|---|---|---|---|---|
| baseline | 62 | 62.9% (39/62; 50-74) | 60.7% (34/56; 48-72) | 77.3% (34/44; 63-87) | 0.680 | 39.3% (22/56; 28-52) | 0.0% (0/13; 0-23) | 13/43/6/0 | 9.2 / 12.4 ms | 0.0000 |
| haiku | 62 | 82.3% (51/62; 71-90) | 97.1% (34/35; 85-99) | 77.3% (34/44; 63-87) | 0.861 | 2.9% (1/35; 1-15) | 0.0% (0/10; 0-28) | 10/25/27/0 | 10585 / 11827 ms | 0.0062 |
| sonnet | 62 | 74.2% (46/62; 62-83) | 100.0% (28/28; 88-100) | 63.6% (28/44; 49-76) | 0.778 | 0.0% (0/28; 0-12) | 0.0% (0/10; 0-28) | 10/18/34/0 | 9444 / 13049 ms | 0.0117 |
| sonnet-low | 62 | 74.2% (46/62; 62-83) | 100.0% (28/28; 88-100) | 63.6% (28/44; 49-76) | 0.778 | 0.0% (0/28; 0-12) | 0.0% (0/10; 0-28) | 10/18/34/0 | 9331 / 11055 ms | 0.0112 |

**test (n = 150)**

| Strategy | n | Accuracy | Dup precision | Dup recall | F1 | False merges (links) | False merges (auto) | auto/suggest/new/failed | p50 / p95 latency | $ / request |
|---|---|---|---|---|---|---|---|---|---|---|
| baseline | 150 | 71.3% (107/150; 64-78) | 71.6% (101/141; 64-78) | 80.8% (101/125; 73-87) | 0.759 | 28.4% (40/141; 22-36) | 10.2% (6/59; 5-20) | 59/82/9/0 | 6.2 / 8.2 ms | 0.0000 |
| haiku | 150 | 91.3% (137/150; 86-95) | 97.4% (113/116; 93-99) | 90.4% (113/125; 84-94) | 0.938 | 2.6% (3/116; 1-7) | 2.4% (1/41; 0-13) | 41/75/34/0 | 10111 / 11441 ms | 0.0060 |
| sonnet | 150 | 74.7% (112/150; 67-81) | 100.0% (87/87; 96-100) | 69.6% (87/125; 61-77) | 0.821 | 0.0% (0/87; 0-4) | 0.0% (0/34; 0-10) | 34/53/63/0 | 9151 / 11170 ms | 0.0112 |
| sonnet-low | 150 | 75.3% (113/150; 68-82) | 100.0% (88/88; 96-100) | 70.4% (88/125; 62-78) | 0.826 | 0.0% (0/88; 0-4) | 0.0% (0/35; 0-10) | 35/53/62/0 | 8895 / 10062 ms | 0.0108 |

**test: Robert's handwritten cases**

| Strategy | n | Accuracy | Dup precision | Dup recall | F1 | False merges (links) | False merges (auto) | auto/suggest/new/failed | p50 / p95 latency | $ / request |
|---|---|---|---|---|---|---|---|---|---|---|
| baseline | 17 | 76.5% (13/17; 53-90) | 76.5% (13/17; 53-90) | 81.2% (13/16; 57-93) | 0.788 | 23.5% (4/17; 10-47) | 12.5% (1/8; 2-47) | 8/9/0/0 | 6.8 / 9.0 ms | 0.0000 |
| haiku | 17 | 88.2% (15/17; 66-97) | 100.0% (14/14; 78-100) | 87.5% (14/16; 64-97) | 0.933 | 0.0% (0/14; 0-22) | 0.0% (0/6; 0-39) | 6/8/3/0 | 9807 / 12162 ms | 0.0060 |
| sonnet | 17 | 64.7% (11/17; 41-83) | 100.0% (10/10; 72-100) | 62.5% (10/16; 39-82) | 0.769 | 0.0% (0/10; 0-28) | 0.0% (0/4; 0-49) | 4/6/7/0 | 9434 / 10895 ms | 0.0112 |
| sonnet-low | 17 | 64.7% (11/17; 41-83) | 100.0% (10/10; 72-100) | 62.5% (10/16; 39-82) | 0.769 | 0.0% (0/10; 0-28) | 0.0% (0/4; 0-49) | 4/6/7/0 | 8647 / 10438 ms | 0.0108 |

**test: paraphrase slice**

| Strategy | n | Accuracy | Dup precision | Dup recall | F1 | False merges (links) | False merges (auto) | auto/suggest/new/failed | p50 / p95 latency | $ / request |
|---|---|---|---|---|---|---|---|---|---|---|
| baseline | 25 | 64.0% (16/25; 45-80) | 69.6% (16/23; 49-84) | 64.0% (16/25; 45-80) | 0.667 | 30.4% (7/23; 16-51) | 0.0% (0/4; 0-49) | 4/19/2/0 | 6.5 / 18.3 ms | 0.0000 |
| haiku | 25 | 88.0% (22/25; 70-96) | 95.7% (22/23; 79-99) | 88.0% (22/25; 70-96) | 0.917 | 4.3% (1/23; 1-21) | 0.0% (0/3; 0-56) | 3/20/2/0 | 10138 / 10962 ms | 0.0060 |
| sonnet | 25 | 76.0% (19/25; 57-89) | 100.0% (19/19; 83-100) | 76.0% (19/25; 57-89) | 0.864 | 0.0% (0/19; 0-17) | 0.0% (0/4; 0-49) | 4/15/6/0 | 9549 / 11537 ms | 0.0111 |
| sonnet-low | 25 | 76.0% (19/25; 57-89) | 100.0% (19/19; 83-100) | 76.0% (19/25; 57-89) | 0.864 | 0.0% (0/19; 0-17) | 0.0% (0/4; 0-49) | 4/15/6/0 | 8801 / 10670 ms | 0.0108 |

**test: same solution, different need**

| Strategy | n | Accuracy | Dup precision | Dup recall | F1 | False merges (links) | False merges (auto) | auto/suggest/new/failed | p50 / p95 latency | $ / request |
|---|---|---|---|---|---|---|---|---|---|---|
| baseline | 25 | 88.0% (22/25; 70-96) | 88.0% (22/25; 70-96) | 88.0% (22/25; 70-96) | 0.880 | 12.0% (3/25; 4-30) | 11.1% (2/18; 3-33) | 18/7/0/0 | 6.3 / 8.0 ms | 0.0000 |
| haiku | 25 | 88.0% (22/25; 70-96) | 100.0% (22/22; 85-100) | 88.0% (22/25; 70-96) | 0.936 | 0.0% (0/22; 0-15) | 0.0% (0/11; 0-26) | 11/11/3/0 | 10354 / 11441 ms | 0.0062 |
| sonnet | 25 | 64.0% (16/25; 45-80) | 100.0% (16/16; 81-100) | 64.0% (16/25; 45-80) | 0.780 | 0.0% (0/16; 0-19) | 0.0% (0/9; 0-30) | 9/7/9/0 | 9330 / 10116 ms | 0.0114 |
| sonnet-low | 25 | 68.0% (17/25; 48-83) | 100.0% (17/17; 82-100) | 68.0% (17/25; 48-83) | 0.810 | 0.0% (0/17; 0-18) | 0.0% (0/9; 0-30) | 9/8/8/0 | 9137 / 10148 ms | 0.0111 |

**test: different solution, same need**

| Strategy | n | Accuracy | Dup precision | Dup recall | F1 | False merges (links) | False merges (auto) | auto/suggest/new/failed | p50 / p95 latency | $ / request |
|---|---|---|---|---|---|---|---|---|---|---|
| baseline | 25 | 92.0% (23/25; 75-98) | 92.0% (23/25; 75-98) | 92.0% (23/25; 75-98) | 0.920 | 8.0% (2/25; 2-25) | 0.0% (0/6; 0-39) | 6/19/0/0 | 6.2 / 7.2 ms | 0.0000 |
| haiku | 25 | 88.0% (22/25; 70-96) | 100.0% (22/22; 85-100) | 88.0% (22/25; 70-96) | 0.936 | 0.0% (0/22; 0-15) | 0.0% (0/5; 0-43) | 5/17/3/0 | 10160 / 11502 ms | 0.0061 |
| sonnet | 25 | 64.0% (16/25; 45-80) | 100.0% (16/16; 81-100) | 64.0% (16/25; 45-80) | 0.780 | 0.0% (0/16; 0-19) | 0.0% (0/2; 0-66) | 2/14/9/0 | 9401 / 12299 ms | 0.0113 |
| sonnet-low | 25 | 60.0% (15/25; 41-77) | 100.0% (15/15; 80-100) | 60.0% (15/25; 41-77) | 0.750 | 0.0% (0/15; 0-20) | 0.0% (0/2; 0-66) | 2/13/10/0 | 9319 / 9914 ms | 0.0109 |

**test: hard negatives**

| Strategy | n | Accuracy | Dup precision | Dup recall | F1 | False merges (links) | False merges (auto) | auto/suggest/new/failed | p50 / p95 latency | $ / request |
|---|---|---|---|---|---|---|---|---|---|---|
| baseline | 25 | 68.0% (17/25; 48-83) | 68.0% (17/25; 48-83) | 70.8% (17/24; 51-85) | 0.694 | 32.0% (8/25; 17-52) | 20.0% (2/10; 6-51) | 10/15/0/0 | 6.5 / 7.7 ms | 0.0000 |
| haiku | 25 | 84.0% (21/25; 65-94) | 91.3% (21/23; 73-98) | 87.5% (21/24; 69-96) | 0.894 | 8.7% (2/23; 2-27) | 14.3% (1/7; 3-51) | 7/16/2/0 | 10214 / 11425 ms | 0.0061 |
| sonnet | 25 | 52.0% (13/25; 33-70) | 100.0% (12/12; 76-100) | 50.0% (12/24; 31-69) | 0.667 | 0.0% (0/12; 0-24) | 0.0% (0/4; 0-49) | 4/8/13/0 | 8877 / 10055 ms | 0.0112 |
| sonnet-low | 25 | 56.0% (14/25; 37-73) | 100.0% (13/13; 77-100) | 54.2% (13/24; 35-72) | 0.703 | 0.0% (0/13; 0-23) | 0.0% (0/5; 0-43) | 5/8/12/0 | 9005 / 10227 ms | 0.0108 |

**test: new needs**

| Strategy | n | Accuracy | Dup precision | Dup recall | F1 | False merges (links) | False merges (auto) | auto/suggest/new/failed | p50 / p95 latency | $ / request |
|---|---|---|---|---|---|---|---|---|---|---|
| baseline | 24 | 25.0% (6/24; 12-45) | 0.0% (0/18; 0-18) | n/a | n/a | 100.0% (18/18; 82-100) | 100.0% (2/2; 34-100) | 2/16/6/0 | 5.6 / 7.4 ms | 0.0000 |
| haiku | 24 | 100.0% (24/24; 86-100) | n/a | n/a | n/a | n/a | n/a | 0/0/24/0 | 9594 / 10993 ms | 0.0058 |
| sonnet | 24 | 100.0% (24/24; 86-100) | n/a | n/a | n/a | n/a | n/a | 0/0/24/0 | 9033 / 10095 ms | 0.0109 |
| sonnet-low | 24 | 100.0% (24/24; 86-100) | n/a | n/a | n/a | n/a | n/a | 0/0/24/0 | 8521 / 9567 ms | 0.0105 |

**Prompt injection** (test: 2 cases; dev: R07). A hijack is an auto-link to a wrong need.

| Strategy | Right decision | Hijacks |
|---|---|---|
| baseline | 100.0% (3/3; 44-100) | 0 of 3 |
| haiku | 66.7% (2/3; 21-94) | 0 of 3 |
| sonnet | 33.3% (1/3; 6-79) | 0 of 3 |
| sonnet-low | 33.3% (1/3; 6-79) | 0 of 3 |

**Calibration on test: accuracy by routing-score bucket** (the baseline's score is its similarity)

| Strategy | [0.0, 0.5) | [0.5, 0.6) | [0.6, 0.7) | [0.7, 0.8) | [0.8, 0.9) | [0.9, 1.0] |
|---|---|---|---|---|---|---|
| baseline | - | 0.0% (0/1; 0-79) | 60.7% (17/28; 42-76) | 67.8% (61/90; 58-77) | 93.3% (28/30; 79-98) | 100.0% (1/1; 21-100) |
| haiku | 70.6% (24/34; 54-83) | - | 100.0% (5/5; 57-100) | 100.0% (28/28; 88-100) | 95.2% (40/42; 84-99) | 97.6% (40/41; 87-100) |
| sonnet | 39.7% (25/63; 29-52) | - | 100.0% (3/3; 44-100) | 100.0% (19/19; 83-100) | 100.0% (31/31; 89-100) | 100.0% (34/34; 90-100) |
| sonnet-low | 40.3% (25/62; 29-53) | - | 100.0% (4/4; 51-100) | 100.0% (18/18; 82-100) | 100.0% (31/31; 89-100) | 100.0% (35/35; 90-100) |

**Auto-link threshold on the routing score** (chosen on dev: lowest score with precision ≥ 0.97 on ≥ 10 links; confirmed on test)

| Strategy | T_auto (dev) | lowest same_need score on dev | dev precision at T | test precision at T | test coverage of true duplicates | unreviewed false merges on test at T / at 0.90 |
|---|---|---|---|---|---|---|
| haiku | 0.6953 | 0.6953 | 97.1% (34/35; 85-99) | 97.3% (109/112; 92-99) | 87.2% (109/125; 80-92) | 3 / 1 |
| sonnet | 0.7506 | 0.7506 | 100.0% (28/28; 88-100) | 100.0% (74/74; 95-100) | 59.2% (74/125; 50-67) | 0 / 0 |
| sonnet-low | 0.7506 | 0.7506 | 100.0% (28/28; 88-100) | 100.0% (74/74; 95-100) | 59.2% (74/125; 50-67) | 0 / 0 |

**Cascade check** (decided on dev, confirmed on test; the cascade sends Haiku's suggest band to Sonnet 5.5)

- **dev.** On Haiku's confident cases (auto band, n = 10): Haiku 100.0% (10/10; 72-100), Sonnet 100.0% (10/10; 72-100). On the band a cascade would escalate (suggest, n = 25): Haiku 96.0% (24/25; 80-99), Sonnet 72.0% (18/25; 52-86). 10 of Haiku's misses sit in its new band, which a cascade never escalates. Cascade: accuracy 72.6% (45/62; 60-82), $0.0101/request; sonnet-low: 74.2% (46/62; 62-83), $0.0112/request; haiku alone: 82.3% (51/62; 71-90), $0.0062/request.
- **test.** On Haiku's confident cases (auto band, n = 41): Haiku 97.6% (40/41; 87-100), Sonnet 80.5% (33/41; 66-90). On the band a cascade would escalate (suggest, n = 75): Haiku 97.3% (73/75; 91-99), Sonnet 72.0% (54/75; 61-81). 10 of Haiku's misses sit in its new band, which a cascade never escalates. Cascade: accuracy 78.7% (118/150; 71-84), $0.0104/request; sonnet-low: 75.3% (113/150; 68-82), $0.0108/request; haiku alone: 91.3% (137/150; 86-95), $0.0060/request.

The injection misses are not injection effects. R07 and T130 were the persona over-split described in failures 1 and 2; no strategy auto-linked an injection to a wrong need.

### Cascade decision: not worth building

ADR 0006 asks two questions, on dev, with test as confirmation.
1. **Are Haiku's high-confidence decisions as accurate as Sonnet's?** On dev, yes: 10/10 for both on Haiku's auto band. Test disagrees (Haiku 40/41, Sonnet 33/41), but test only confirms.
2. **Would a cascade beat Sonnet-low?** No.
   - The cascade sends Haiku's gray zone (its suggest band) to Sonnet, and on exactly that band Sonnet is the weaker judge: 18/25 against Haiku's 24/25 on dev, 54/75 against 73/75 on test.
   - The simulated cascade reaches 72.6% (60-82) on dev, below Sonnet-low (74.2%) and Haiku alone (82.3%), at a cost between the two. Test confirms: 78.7% against 91.3% for Haiku alone.
   - 10 of Haiku's misses sit in its new band, which a cascade never escalates.

**Not built.**

### Recommendation

**Use Haiku 4.5 for both extraction and adjudication.**
- **On dev, where the choice is made,** Haiku and Sonnet overlap on accuracy: 82.3% (71-90) against 74.2% (62-83), with Sonnet-low identical. Your rule says the simpler strategy wins. Haiku is one model for both steps at about half the cost ($0.0062 vs $0.0117 per request) and similar latency.
- **Test confirms with room to spare:** 91.3% (86-95) against 74.7% (67-81). Haiku's duplicate F1 is 0.938 against 0.821.
- **What Sonnet does better:** it never false-merges (0 of 87 links on test). It pays with recall of about 70%, because it often labels a true duplicate `related` when the persona differs, and it sends 63 of 150 requests to new needs where 25 are expected.

**Against the baseline, said plainly:**
- **Only Haiku clearly beats it.** On dev accuracy, Haiku's and the baseline's intervals barely overlap (71-90 vs 50-74). The separation is on links: duplicate precision 97.1% (85-99) against 60.7% (48-72), and false merges 2.9% against 39.3%. On test everything separates: accuracy 91.3% against 71.3% (64-78), and new needs 100% against 25%.
- **Sonnet with `adjudicate_v1` does not beat the baseline on accuracy** on either split: dev 74.2% (62-83) vs 62.9% (50-74); test 74.7% (67-81) vs 71.3% (64-78). It even loses to it on the same-solution, different-solution, hard-negative and handwritten slices. It wins only on false merges. Under CLAUDE.md rule 7, Sonnet hasn't earned its cost on accuracy; Haiku has.

**Caveats.**
- The data is synthetic.
- The ranking holds for prompt `adjudicate_v1`, whose persona rule hurts both models, Sonnet more. A v2 prompt needs a new run, and could narrow the gap.

**Auto-link threshold on the routing score, for Haiku: T_auto = 0.70** (0.6953).
- **The rule:** this is the lowest score at which dev precision is at least 0.97 on 10 or more links: 97.1%, 34/35 (85-99).
- **Confirmed on test:** 97.3%, 109/112 (92-99), with 87.2% of true duplicates auto-linked.
- **Read it carefully:**
  - The sweep is degenerate. 0.6953 is exactly the lowest same_need score Haiku produced on dev, so the precision bar never binds. The real choice is between auto-linking every same_need label and holding some back for review, not a calibrated cut-off.
  - The routing score doesn't separate Haiku's errors. Its three wrong links on test score 0.81, 0.86 and 0.93, while everything between 0.6 and 0.8 was right.
  - At 0.70, test has 3 unreviewed false merges against 1 at the current 0.90. 0.90 auto-links only 32% of true duplicates.
  - The interval's lower end (92%) means a false-merge rate of up to about 8% can't be ruled out, against the M4 target of ≤ 3%.
  - The score is built on placeholder s_min/s_max and weights. Recalibrating them changes the score, and T must be chosen again.
- **My recommendation:** take 0.70, and keep the 10% audit sample, so M4 is measured on real traffic and not assumed.

Prompts and config are unchanged, as asked.

### The 5 most informative failures (test)

1. **H010, "Log in with Google" (Marketing Coordinator), expected sso.** Both models: sso is `related`, so it becomes a new need.
   - *Hypothesis:* need titles name a single persona ("IT admins need to sign in through their identity provider"), and `adjudicate_v1` says a different persona means `related`. An end user asking to log in with Google has the same problem from the other side.
   - The rule should compare problems, and accept that a need's beneficiaries span roles. The R07 smoke-run miss (§2) is the same failure.
2. **H006, "PDF of the exec dashboard" (Chief of Staff), expected share_kpis.** Both models: `related`.
   - *Hypothesis:* the same mechanism. The need says "Team leads need to get KPIs to people who have no login", and an exec persona doesn't match.
   - It is Haiku's dominant failure: 12 of its 13 test misses labelled the true need `related`, and in 11 of them the extracted persona differs from the need's. When the persona differs, Haiku says `related` 11 times out of 58; when it matches, once in 67.
   - Sonnet does it more often, but not always: it still says same_need 31 times out of 58 when the persona differs. It also has 11 `related` misses where the persona matches, so a second cause is at work there.
3. **T065, "Write Brightboard data back to Snowflake", expected data_portability.** Haiku **auto-linked** it to snowflake at 0.93: the only auto-link false merge on test.
   - *Hypothesis:* the signals are correlated. The extraction read it as data_engineer and data_sources (defensible for "push datasets into Snowflake"). Those fields match the Snowflake need, so field agreement added 0.2 to a label that was already wrong. Without the field matches, the score would be 0.73: a suggestion, not an auto-link.
   - Field agreement is not independent of the label.
   - The label itself (data_portability for reverse ETL) is also debatable, like T050. All three Sonnet runs called it a new need.
4. **T084, "Investors want a monthly snapshot" (CFO), expected share_kpis.** Haiku suggested excel_finance.
   - *Hypothesis:* the requester's role (CFO) drives the extracted persona (finance), which pulls toward the finance need, even though the job is sharing KPIs with outsiders. The role is evidence, not the answer. The prompt could say so.
5. **T050, "BigQuery connector", expected a new need.** Haiku suggested snowflake (same_need); Sonnet said `related`.
   - *Hypothesis:* the label may be the problem. "A native connector to our warehouse" is arguably one need, and the ground truth makes it Snowflake-only.
   - Worth a human decision. If the need is "warehouse connectors", this is a labelling fix, not a model fix. It is one of the generated cases (`reviewed_by_human: false`).
