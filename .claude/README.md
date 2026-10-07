# Claude Code harness

A reusable `.claude/` folder for any repository where every prompt to Claude Code must be logged, and where you want the coding agent held to test-first work and safe defaults. Nothing in it is tied to one project: project details live in the project's CLAUDE.md, and project-specific permissions are added to `settings.json` when you install it.

## What's inside

| Path | What it does |
|---|---|
| `hooks/log_prompt.py` | UserPromptSubmit: appends every raw prompt to `prompts.audit.jsonl`, with the size and hash of `prompts.txt` at that moment. Prints nothing. |
| `hooks/guard_prompt_log.py` | PreToolUse: keeps `prompts.txt` and `prompts.audit.jsonl` append-only. It reads shell commands the way a shell does (heredoc bodies skipped, every line checked, `cd` followed, paths resolved), so appends, reads and commit messages pass and rewrites are blocked. Subagents can't write the log. |
| `hooks/require_prompt_log.py` | Stop: sends Claude back once if `prompts.txt` hasn't grown since the prompt arrived, or if earlier entries changed. Checks the effect, not timestamps. Never loops. |
| `hooks/format_python.py` | PostToolUse: runs the project's own ruff (the nearest `.venv/bin/ruff` above the edited file) to fix and format it. Keeps imports added for the next edit. No-op if there's no ruff. |
| `hooks/test_hooks.py` | 28 tests, including about 90 real commands that must be allowed or blocked. Run: `python3 -m unittest discover -s .claude/hooks -v` |
| `settings.json` | Wires the hooks. Allows routine git, `date` and the hook tests; asks before `git push`; denies reading `.env`, editing the audit file and force pushes. Keeps every Bash command in the project root and runs subagents in the foreground, so each turn gets one complete log entry. |
| `rules/llm-code.md` | Loaded only when Claude touches model-calling code or evals: current Claude model IDs and API restrictions, structured outputs, error handling, prompt versioning, the baseline and eval rules. |
| `rules/testing.md` | Loaded only for tests and evals: test-first, eval-first, no network, never assert on fakes or weaken tests. |
| `rules/frontend.md` | Loaded only for frontend code: generated API types, one data layer, labelled AI output, test IDs. |
| `agents/reviewer.md` | A reviewer subagent with no edit tools, checking correctness, AI risks, security and tests. |
| `skills/tdd` | The red, then green loop, with the evidence recorded in `prompts.txt`. |
| `skills/quality-gate` | Runs the project's full check and fixes failures without weakening tests. |
| `skills/eval-report` | Runs paid evals only when you invoke `/eval-report`, after stating the cost. |

## Install in a project

1. Copy this folder to the repo root as `.claude/`. Do it after the CLAUDE.md that defines the logging rule exists.
2. Start a new Claude Code session in the repo root, so the hooks, settings, subagent and skills all load. Check with `/hooks`, `/skills` and `@reviewer`.
3. Add the project's own permissions to `settings.json`: allow its routine commands (for example `Bash(make *)`, `Bash(uv run *)`, `Bash(npm run *)`), and add an ask rule for anything that spends money (for example `Bash(make eval *)`). Ask rules apply in every permission mode.
4. Make the project's check command run the hook tests, and list the check and eval commands under "Commands" in CLAUDE.md. The skills read them from there.

## Requirements

`python3` 3.8 or later on PATH. No third-party packages. ruff is optional.
