---
name: quality-gate
description: Run the project's full quality gate (lint, types, tests) and report pass or fail with the failing output. Use before committing a code change and before declaring it done; docs-only changes skip it.
---
Run the full check command listed under Commands in CLAUDE.md (by convention `make check`) from the repo root. Skip it for a docs-only change.

- If it passes, report "Quality gate: pass" with the test count.
- If it fails, show the first failing output of each failing step, fix the cause (never by weakening, skipping or deleting tests), and run it again. After three failed rounds, stop and report what still fails and why.
