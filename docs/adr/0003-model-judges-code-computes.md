# 0003. The model judges, code computes, including the routing score

Status: accepted, 2026-10-07

## Context
CLAUDE.md rule 1: models return labels, extracted fields, ratings and rationales, while thresholds, routing, scores and permissions are code. A confidence the model states about itself is poorly calibrated and drifts with prompt and model changes, so routing on it would make automation depend on its least reliable output.

## Decision
- The adjudicator returns, per candidate need, a label (same_need, related or different), a stated confidence, a rationale and quotes. The confidence is stored and shown, but not used for routing.
- Code computes the routing score from three signals: the label, the best embedding similarity (normalized with s_min and s_max), and whether the extracted fields agree (product area, persona). The score is 0 unless the label is same_need; otherwise it is `w_L + w_s·sim_norm + w_f·fields` (spec section 8).
- Weights and thresholds live in `config/routing.yaml`. Prioritization (demand, urgency, priority) is pure code over `config/priorities.yaml`. The model only rates strategic fit (0-3 with a quote), and code verifies the quote and combines it.
- The no-LLM baseline runs through the same routing code, with the label replaced by a similarity threshold.

## Alternatives rejected
- **Routing on the model's stated confidence.** Uncalibrated, and not reproducible across prompt versions.
- **The model outputs a priority score.** It can't be audited or reproduced, it drifts, and it invites "the AI ranked our roadmap".
- **A learned classifier over the signals.** Too little labelled data (about 150 pairs) to train and validate one. Hand-set weights tuned on the dev split are more honest at this size.

## Consequences
- Every number in the UI can be explained from its inputs and is covered by unit tests, written first.
- A prompt or model change can move the labels but not the policy. Its effect shows up in the eval (rule 7).
- The weights are a judgment call tuned on synthetic data (assumption A1). They are revisited using the audit sample (ADR 0004).

## Outcome (2026-10-07, evals/REPORT.md §3 and §4.3)
- **The routing score stays as built, placeholders included** (weights 0.5/0.3/0.2, s_min 0.55, s_max 0.85).
- **Right now it adds little over the label.** Every dev same_need label from Haiku scores at or above the chosen threshold, and Haiku's three test errors score 0.81, 0.86 and 0.93, while everything between 0.6 and 0.8 was right.
- **Field agreement is not independent of the label,** because both come from the same extraction (T065). Without it, T065 would still score 0.73, an auto-link at 0.6953.
- **Recalibrating** s_min, s_max and the weights would change the score and force a new threshold. That is not worth doing until a harder dev set shows the score separating errors.
- **The safeguard against a wrong label is the audit sample and undo (ADR 0004), not the score.**

