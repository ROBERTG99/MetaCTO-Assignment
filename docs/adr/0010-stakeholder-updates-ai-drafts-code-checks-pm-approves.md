# 0010. Stakeholder updates: the AI drafts, code checks commitments, the PM approves

Status: accepted, 2026-10-07

## Context
"Keep stakeholders informed about decisions and progress" is the pain the brief lists that teams most often skip. It is also where trust is won or lost. A message to a customer is an external commitment, so a wrong promise costs more than a late message. Writing one personal note per supporter by hand is exactly the work that doesn't happen.

## Decision
- **A status change is a human decision with a reason.** `PATCH /needs/{id}/status` takes the status, the PM's reason and an optional target date. It saves the change at once, with an append-only `NeedStatusChange` row, so the decision never waits on a model.
- **The AI drafts in the background.** The status-change row is also a worker job, following the ADR 0007 pattern. `stakeholder_update_v1` on FAST_MODEL makes one call per change and drafts:
  - a personal update for each supporter (authors of member requests and confirmed supporters), referring to what that person asked for;
  - an internal note for customer success for each affected account.
  - Code checks that everyone gets exactly one draft, with one repair retry. Offline mode drafts from a fixed template, so the flow works without a key.
- **Code checks commitments.** `app/ai/commitments.py` flags dates, relative timing ("next week", "soon", "Q1") and delivery promises ("we will ship", "will be released") unless the PM entered a date. With a date, only a different date is flagged. The model is told the same rule, but it isn't trusted to follow it.
- **Nothing goes out on its own.** A draft reaches the simulated outbox only through approval. Approval re-runs the check on the approved text, and refuses while anything is flagged (409 `commitments_flagged`).
  - Approving a personal update writes a `Notification` with a timestamp for that supporter.
  - M3 (decision-loop latency) is the median time from the status change to the last supporter's notification.
- **Requesters see only their own updates.** The API returns only approved personal updates on a need, and only the approved copy (`approved_body`), never an edit made later. CS notes stay in the PM view. The browser filters to the current requester; with no auth (spec A3), that last filter is client-side.
- **Approval can't race.** Approve, edit and discard are compare-and-set on `status = draft`, so an edit can't land on an approved message and a double click can't send twice.
- **A newer decision supersedes older drafts.** A newer status change marks the previous change's unsent drafts superseded, so they can't be sent. A drafting job that hasn't run yet is skipped without a model call.
- **A failed drafting job can be run again.** The PM can retry from the failed card (`POST /needs/{id}/status-changes/{cid}/redraft`).

## Alternatives rejected
- **Auto-send clean drafts.** It removes the PM from external commitments, and a clean check doesn't prove a message is right, only that it makes no dated promise.
- **Ask the model whether a draft makes promises.** That's a second model judging the first, and its errors would be invisible. A deterministic check is auditable, testable and free. Its known weakness: it misses commitments phrased without timing words ("this is top of our list").
- **One generic update per need.** It's cheaper, but it doesn't refer to what each person asked for, which is the point.
- **Draft synchronously in the request.** The PM would wait on a model, and a provider failure would block a product decision (CLAUDE.md rule 2).

## Consequences
- **Cost:** one Haiku call per status change, about $0.005 for a need with five supporters.
- **Check limits:** the check gives false positives ("Q1 revenue" in a quote) and false negatives (promises without timing words, like "this is top of our list"). Both are visible to the PM, who reads every draft before approving.
  - **Timing with a PM date:** when the PM sets a date, relative timing ("next week") passes even if it contradicts that date. This follows the rule as asked ("unless the PM entered a date"); the review suggested flagging it anyway, and that is the next refinement if it matters.
  - **What is covered:** curly apostrophes, months without a day, "in two weeks", "tomorrow", "by Friday" and EOY are caught. Fractions like 24/7 or 10/12 aren't dates.
- **Cross-supporter leakage:** one call sees every supporter's request text, and code only checks that ids are covered. A draft could mention another supporter's words, and PM review is the only guard. Batching per supporter would remove that at about 5 times the calls.
- **Size limit:** the output limit scales with the number of recipients, up to 16k tokens, and each supporter's text is capped at 500 characters. A need with about 60 or more recipients would need batching.
- **No eval yet:** `stakeholder_update_v1` has no eval (rule 7). The safety net is the code check plus human approval of every message. An eval with fabricated-commitment cases is the next step before relying on draft quality.
- **Simulated delivery:** delivery is the simulated outbox (`GET /outbox`) plus the requester's need page. A real channel (email, Slack) would read the outbox.
