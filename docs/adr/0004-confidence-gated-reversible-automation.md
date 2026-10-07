# 0004. Confidence-gated, reversible automation with an audit sample

Status: accepted, 2026-10-07

## Context
Auto-linking is what removes PM work (metric M1). A false merge, though, silently hides a request inside the wrong need: demand is miscounted and customers get the wrong update. Nobody reviews auto-links, so without a sample the false-merge rate can't be measured; the undo rate only gives a lower bound. Requesters who click "this is my need" also over-claim.

## Decision
- **Three bands, on the routing score (ADR 0003).**
  - At or above T_auto (start high: 0.90): auto_linked, labelled with its source, score and rationale, listed in the inbox's read-only Auto-linked tab, and undoable in one click.
  - Between T_suggest and T_auto: a suggestion in the PM inbox.
  - Below T_suggest: a new need, with related candidates shown on the request as a suggestion only.
  - Matches CLAUDE.md rule 2.
- **Audit sample.** An auto-link is sampled when `sha256(request_id) mod 10 == 0`, about 10%, reproducible and testable. Sampled links appear in the inbox's Audit tab, and the PM marks each correct or false_merge; that gives metric M4 with a Wilson interval. A false_merge verdict also undoes the link, so it stops counting as demand, and the request returns to Suggestions.
- **Requester claims.** The claimed need is always added to the adjudicated candidates. A claimed link starts active. It stays confirmed only if the adjudicator says same_need and the score is at least T_suggest; otherwise it becomes disputed, goes to the inbox, and is excluded from demand until a PM decides. The same happens if the request ends in needs_review.
- **Nothing is deleted.** Links move between proposed, active, disputed, rejected and undone, and every change is an event (rule 6).
- **Thresholds come from evals.** They are set on the dev split and confirmed on the test split. They are lowered only when the audited false-merge upper bound stays within target.

## Alternatives rejected
- **Suggestions only, no automation.** Safe, but M1 stays near 0 and the workflow doesn't change (Q4).
- **Full automation with no audit.** The false-merge rate couldn't be measured, and the M4 guardrail would be fiction.
- **Random sampling with a seeded RNG.** Harder to reproduce across runs than a hash of the id.

## Consequences
- The PM's work is the gray zone, disputes, failures and the 10% audit. The audit is reported separately from M1, as the cost of measuring.
- Starting with a high T_auto means fewer auto-links at first. That is deliberate: automation grows as the audit earns trust.
- At about 10% sampling, a tight bound on false merges needs a few hundred auto-links. With synthetic data, the bound stays wide, and the report says so.
