---
paths:
  - "**/tests/**"
  - "**/test_*.py"
  - "**/*_test.py"
  - "**/*.test.ts"
  - "**/*.test.tsx"
  - "**/e2e/**"
  - "evals/**"
---
# Testing rules

- Deterministic logic (policies, scoring, validation, parsing, API contracts, metric functions) is test-first: write the tests, run them and show they fail for the right reason, then implement. Use the `tdd` skill.
- AI behavior is eval-first: the labelled cases exist before the prompt that has to pass them.
- One behavior per test, named after the behavior.
- No network in unit or API tests: fake model clients, fake embedders, temporary or in-memory databases.
- Never assert on what a fake returns; assert on what the code under test does with it.
- Never weaken an assertion, skip a test or delete one to get green. If a test is wrong, say why and fix it in its own commit.
- UI golden paths are end-to-end specs that run against seeded data without network access.
