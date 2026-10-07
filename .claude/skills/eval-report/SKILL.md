---
name: eval-report
description: Run the paid AI evals and add a dated comparison to the eval report. Only when I invoke it.
disable-model-invocation: true
---
Evals call a paid API, so this skill only runs when I invoke it (`/eval-report`, optionally with arguments such as a strategy or split).

1. Check that the API key is set (never print it). State how many model calls the run will make and its rough cost, and wait for my go.
2. Run the project's eval command (listed under Commands in CLAUDE.md) on the dev split, then the test split, passing on any arguments I gave.
3. Add a dated section to the eval report: git sha, strategies, models, prompt versions, the metrics table with n and 95% intervals, the no-LLM baseline, and the delta against the previous section. Never rewrite earlier sections.
4. List the 5 most informative failures, each with a hypothesis. Tune on dev only; test is for reporting.
