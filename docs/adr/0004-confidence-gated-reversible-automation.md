# 0004. Confidence-gated, reversible automation with an audit sample

Status: accepted, 2026-10-07

## Context
Auto-linking is what removes PM work (metric M1). A false merge, though, silently hides a request inside the wrong need: demand is miscounted and customers get the wrong update. Nobody reviews auto-links, so without a sample the false-merge rate can't be measured; the undo rate only gives a lower bound. Requesters who click "this is my need" also over-claim.

## Decision
- **Three bands, on the routing score (ADR 0003).**
  - At or above T_auto (start high: 0.90): auto-linked (need_id set, suggestion `applied`), labelled with its source, score and rationale, listed in the inbox's read-only Auto-linked tab, and undoable in one click.
  - Between T_suggest and T_auto: a suggestion in the PM inbox.
  - Below T_suggest: a new need, with related candidates shown on the request as a suggestion only.
  - Matches CLAUDE.md rule 2.
- **Audit sample.** An auto-link is sampled when `sha256(seed:request_id) mod 10000 < rate × 10000` (rate 10%, seed in `config/routing.yaml`): about 10%, reproducible and testable. Sampled links appear in the inbox's Audit tab, and the PM marks each correct or false_merge; that gives metric M4 with a Wilson interval. A false_merge verdict also undoes the link: the request becomes its own need, so it stops counting as demand. An undo of a sampled link that has no verdict yet is recorded as false_merge, so M4 keeps the false merges the PM catches.
- **Requester claims.** "This is my need" creates a support in `claimed` state, which doesn't count as demand. The claimed need is always added to the adjudicated candidates. The claim becomes `confirmed` only if the adjudicator says same_need and the score is at least T_suggest. Otherwise it becomes `disputed` and goes to the inbox, still uncounted, until a PM decides.
- **Nothing is deleted.** `request.need_id` and `support.link_status` hold the current state, and `aisuggestion.state` holds the decision (proposed, applied, accepted, rejected, undone). Every link and unlink is a row in the append-only `linkevent` table, with who made it (auto, pm, requester_claim), when, and the routing score (rule 6).
- **Thresholds come from evals.** They are set on the dev split and confirmed on the test split. They are lowered only when the audited false-merge upper bound stays within target.

## Alternatives rejected
- **Suggestions only, no automation.** Safe, but M1 stays near 0 and the workflow doesn't change (Q4).
- **Full automation with no audit.** The false-merge rate couldn't be measured, and the M4 guardrail would be fiction.
- **Random sampling with a seeded RNG.** Harder to reproduce across runs than a hash of the id.

## Consequences
- The PM's work is the gray zone, disputes, failures and the 10% audit. The audit is reported separately from M1, as the cost of measuring.
- Starting with a high T_auto means fewer auto-links at first. That is deliberate: automation grows as the audit earns trust.
- At about 10% sampling, a tight bound on false merges needs a few hundred auto-links. With synthetic data, the bound stays wide, and the report says so.
