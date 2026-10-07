# 0006. Per-step model choice by eval, behind a provider-agnostic gateway

Status: accepted, 2026-10-07

## Context
Extraction and adjudication may need different models. At about 1-2 cents per request (spec section 9), price doesn't decide the choice; false merges and gray-zone size do. CLAUDE.md requires every model call to go through `app/ai/gateway.py` and be recorded in ai_runs (rule 5), and requires an LLM step to beat the no-LLM baseline (rule 7). Tests never call a real model (rule 8).

## Decision
- **One gateway, several providers.** The gateway has one method per step (`extract`, `adjudicate`, `rate_fit`, `brief`, `agent_step`) and three providers: AnthropicProvider, OfflineProvider (heuristics and the baseline), and FakeLLM for tests.
- **Configuration.** The model per step and the prompt version come from configuration (FAST_MODEL, SMART_MODEL, and per-step overrides). Model IDs are never hard-coded at call sites.
- **Evals decide, on the same frozen splits:**
  - C0: the baseline.
  - C1: Haiku 4.5 everywhere.
  - C2: Haiku 4.5 for extraction, Sonnet 5.5 for adjudication.
  - C3: Sonnet 5.5 at low effort for both steps, as the reference.
  - The cascade (C4: Haiku first, then Sonnet 5.5 re-adjudicates only when the routing score computed from Haiku's label lands in the gray zone) is built only if Haiku's high-confidence answers turn out to be calibrated, and only if it beats C3. "High-confidence" means a routing score at or above T_auto, not the confidence the model states, so ADR 0003 holds. "Calibrated" means that, on dev, Haiku's auto-band decisions are as precise as C3's.
- **Tie-break.** If the 95% intervals of two configurations overlap on the deciding metrics, the simpler and cheaper one wins.
- **Before any live run,** the call count and the expected cost are shown, and Robert says go.
- **Every call** is recorded in ai_runs: step, model, prompt version, tokens, cost, latency and outcome.

## Alternatives rejected
- **One model everywhere, chosen up front.** Not grounded in evidence.
- **The cascade by default.** It saves about 1 cent per request against C2 or C3 ($0.014 vs $0.023), and it needs a calibration that hasn't been shown yet.
- **A multi-provider abstraction library** (LiteLLM or similar). Hides model-specific constraints (Sonnet 5.5 rejects disabling thinking and forcing a tool choice), and we only need one provider plus fakes.

## Consequences
- Changing a model or prompt is a config change plus an eval run recorded in evals/REPORT.md, with the prompt version bumped (rule 7).
- Model-specific rules (structured outputs, effort, stop reasons) live in the provider, not in the pipeline.
- The eval set has to be large enough to separate configurations: about 150 labelled pairs, weighted toward the hard cases (test-plan.md).

## Outcome (2026-10-07, evals/REPORT.md §3)
- **Haiku 4.5 for both steps.** On dev it overlaps with Sonnet 5.5 (82.3% vs 74.2%), so the simpler, cheaper strategy wins. Test confirms: 91.3% (86-95) vs 74.7% (67-81).
- **Sonnet 5.5 with `adjudicate_v1`** has perfect precision but about 70% recall. It does not clearly beat the no-LLM baseline on accuracy.
- **C3 as defined was not measured.** C3 (Sonnet-low for both steps) ran with Haiku extraction, as Robert asked.
- **The cascade was rejected.** Haiku's confident decisions are calibrated on dev, but on the band the cascade would escalate Sonnet is the weaker judge, and the cascade loses to Sonnet-low.
- **Not applied yet.** Config and prompts are unchanged until Robert's go.
- **Not final.** The comparison holds for prompt v1; a v2 needs a new run.

