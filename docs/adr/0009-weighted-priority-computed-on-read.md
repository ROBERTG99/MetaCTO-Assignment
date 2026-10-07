# 0009. Priority is a weighted score computed on read; the model rates goals, code weighs them

Status: accepted, 2026-10-07

## Context
The brief asks to "separate popular requests from strategically valuable ones" and to "prioritize consistently". Brightboard has ARR, renewal dates and pipeline per account, and three written goals. It has no effort estimates yet.

Three frameworks were compared against that data:

| Framework | Needs | Fit here |
|---|---|---|
| RICE (reach × impact × confidence ÷ effort) | Effort, plus a subjective impact and confidence per item | Effort doesn't exist, and impact and confidence would be guesses with no audit trail. Reach maps to accounts, but RICE has no place for goals. |
| WSJF (cost of delay ÷ job size) | Job size, and cost of delay = value + time criticality + risk reduction | Without job size it reduces to cost of delay, which is a weighted score with less explicit weights. |
| Weighted score (demand, strategic fit, urgency) | ARR, segment, renewals, severity, goal ratings | Uses only data we have. Every component can be shown, and the weights are a product decision in one file. |

## Decision
- **Weighted score.** `Priority = 100 × (0.4 D + 0.4 S + 0.2 U)`, with the weights in `config/priorities.yaml` (formulas in spec §8):
  - **D (demand):** log-scaled, segment-weighted revenue over unique accounts.
  - **S (strategic fit):** the goal-weighted ratings.
  - **U (urgency):** the highest severity, plus whether a supporting customer renews within 90 days.
- **Effort later.** When engineering gives sizes, effort becomes a human input and the ranking becomes value ÷ effort, which is WSJF with this score as the value.
- **Computed on read, never stored.** `app/services/priority.py` gathers each need's accounts, severities and ratings and calls the pure functions in `app/scoring.py`. Two reasons:
  - The renewal window moves with the date.
  - A weight change in config re-ranks the backlog on restart, with no code change, no prompt change, no model call and no migration.

  The backlog is small (spec A2), so this is cheap.
- **The model rates, code weighs (CLAUDE.md rule 1).** `strategic_fit_v1` (Haiku 4.5, the FAST_MODEL from REPORT §4.1) returns, per goal, a rating of 0-3, a one-sentence rationale and a quote.
  - Ratings are stored per goal (`GoalRating`, append-only; `Need.fit_run_id` points at the set in use).
  - S is computed with the current goal weights, which the model never sees.
  - The input contains no structured requester fields (role, name, account, segment, revenue). Fit is judged on the problem, because the adjudication evals showed the models keying on the requester's role (REPORT §3).
- **When it runs.** A rating is a job on the need row, run by the worker after requests and claims (the ADR 0007 pattern). It is queued:
  - when a need is created;
  - when its supporting accounts cross 3 or 10 (one rating per crossing, none when support drops);
  - when its last rating failed;
  - when the goals' text has changed since the rating (the status shows "stale" until then).
  - Transient errors retry with backoff up to 3 attempts. Anything else marks the rating failed with the reason, and the ratings in use stay in use.
  - Offline mode has no rater, so needs stay "pending" or show the recorded seed ratings.
- **Popular vs strategic.**
  - **Quadrants:** D ≥ 0.60 is popular and S ≥ 0.50 is strategic, giving clear win, strategic bet, popular but off-strategy, and park.
  - **Where they show:** in `GET /insights/quadrant` and on every need's breakdown.
  - **Owner:** product areas map to owning PM teams in config, and unknown areas go to product-triage.

## Alternatives rejected
- **RICE and WSJF now.** Both need effort, which we don't have. Inventing it would make the ranking look precise when it isn't.
- **Store the score on the need (as before).** Urgency goes stale as dates pass, and a config change needs a backfill. Computing on read removes both problems.
- **Store S, or let the model see the weights.** A weight change would then need a model call, and the model could game the total.
- **Renewal share (renewing ARR ÷ supporting ARR) instead of a yes/no flag.** The brief for this step asked for "whether a renewal falls within 90 days".
  - The flag is simpler to explain, and the renewing accounts are listed.
  - The cost: a $1k renewal adds as much urgency as a $1M one. Demand already carries the size.
  - Revisit if PMs find urgency too coarse.
- **Rating every need on a schedule.** It costs calls with no new information. Crossings are the moments the evidence changes.

## Consequences
- **Explainable scores.** Every need in `GET /needs` carries its breakdown: each component's inputs, the points it contributes, the weights used, the ratings with rationale, quote, model and prompt version, the quadrant and the owner.
- **Unrated needs float up.** Until a need is rated, S is left out and D and U are renormalized. Example from the API tests: an unrated need with a blocker and a renewal scores 64.7 and outranks rated needs. In live mode the rating is queued at creation, so this lasts a few seconds; offline it lasts until the seed's recorded ratings are loaded. The UI must show "not rated" next to the score.
- **Accepted risk: prompt injection in a request can raise S.**
  - **Exposure:** strategic fit is worth up to 40 points of priority, and no PM override exists yet.
  - **Mitigations:**
    - text is passed as data inside tags, and the prompt says so;
    - every rating shows its rationale and quote;
    - S is shown apart from demand;
    - re-rating at 3 and 10 accounts dilutes a single request.
  - **Tested by:** an injection case (F11) in the strategic-fit eval.
  - **Fix:** a PM override (an appended rating with an actor) is the next step if it matters in practice.
- **Calls and cost.** A need costs one Haiku call at creation and at most two more over its life, about $0.004 each. `make seed-live` now also rates the needs it touches.
- **Agreement is measured, not assumed.** Agreement with human ratings is measured on 10 seeded needs plus the injection case (REPORT §5). These cases are for reporting only: there is no dev split, so a v2 prompt would need new cases.
