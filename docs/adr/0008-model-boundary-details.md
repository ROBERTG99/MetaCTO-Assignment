# 0008. The live model boundary: own validation, no refusal fallbacks, claims judged on the reason

Status: accepted, 2026-10-07

## Context
Three details of the AI layer change what reaches the PM, and the first review caught two of them.
- **`messages.parse` hides refusals.** In anthropic 1.11.0 it validates the output inside the SDK before returning. A refusal or a max_tokens stop therefore surfaces as a validation error: the wrong retry is spent, needs_review gets the wrong reason, and a failed call records no tokens.
- **Refusal fallbacks.** The claude-api skill recommends turning on server-side fallbacks for Sonnet 5.5.
- **Claim framing.** The first version framed a claim as "I support this existing need: <title>". That hands the model the answer.

## Decision
- **Our own validation.** The live client calls `messages.create` with `output_config.format` (a JSON schema from the Pydantic model, through `anthropic.transform_schema`). It checks `stop_reason` first: a refusal is a refusal, and max_tokens gets the one retry with a higher limit. It then validates the JSON with Pydantic in our code. Every outcome carries its usage, so failed calls are costed in AIRun. This deviates from `.claude/rules/llm-code.md`, which says to use `parse`; that rule needs updating, which is Robert's call.
- **No refusal fallbacks.** A refusal goes to needs_review with its category (CLAUDE.md rule 2). Keeping one model per step keeps AIRun and the evals attributable to a single model.
- **Claims are judged on the reason.** A claim is checked on the requester's own reason in `<request>`, against the claimed need plus the retrieved candidates. A claim with no reason goes to the inbox without a model call.

## Alternatives rejected
- **Keep `parse` and inspect the exception.** The exception carries neither the stop reason nor the usage.
- **Fallbacks with a model column.** It solves attribution, but a refused request then gets a decision from a model the evals never measured.
- **Show the model the title the requester clicked.** It confirms itself; field agreement would come from the title too.

## Consequences
- The live client has its own tests, against an HTTP mock transport (`tests/unit/test_anthropic_client.py`), with no network.
- Prompt or schema changes still bump the prompt version and need an eval run (rule 7). v1 has no eval run yet, so the LLM path is not validated.
