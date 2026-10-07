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
