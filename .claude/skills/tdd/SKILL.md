---
name: tdd
description: Test-first loop for deterministic logic. Use when implementing policies, scoring, validation, parsing, API contracts, metric functions or any pure function.
---
1. Write tests that describe the behavior: the happy path, edge cases and failure cases. No implementation yet.
2. Run them and show they fail for the right reason (an assertion, not an import or syntax error).
3. Implement the minimum that makes them pass. Run them and show they pass.
4. Refactor if it helps, then run the project's full check (see Commands in CLAUDE.md).
5. In the prompts.txt summary, record red -> green: which tests, how many, and the command.
