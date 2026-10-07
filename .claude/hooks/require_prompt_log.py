#!/usr/bin/env python3
"""Stop hook: don't let a turn end until prompts.txt has an entry for the latest prompt.

log_prompt.py records the size and SHA-256 of prompts.txt when each prompt arrives. When
Claude tries to stop, prompts.txt must be longer than it was then (an entry was appended)
and its first bytes must be unchanged (nothing earlier was edited). This checks the effect,
so it also catches rewrites the PreToolUse guard can't see. Only this session's prompts
count, so a second Claude session in the same repo doesn't interfere.
Exit code 2 keeps Claude working and shows it the message; stop_hook_active prevents loops.
"""

import hashlib
import json
import os
import sys

APPEND = (
    "Append it now with cat >> prompts.txt <<'PROMPT_LOG_END', using the entry format in "
    "CLAUDE.md (Prompt Logging), then finish."
)


def session_entries(path: str, session_id) -> list:
    entries = []
    with open(path, encoding="utf-8", errors="replace") as f:
        for line in f:
            try:
                entry = json.loads(line)
            except ValueError:
                continue
            if isinstance(entry, dict) and (session_id is None or entry.get("session_id") == session_id):
                entries.append(entry)
    return entries


def problem(root: str, session_id) -> str:
    audit, log = os.path.join(root, "prompts.audit.jsonl"), os.path.join(root, "prompts.txt")
    if not os.path.exists(audit):
        return ""
    entries = session_entries(audit, session_id)
    if not entries:
        return ""
    last = entries[-1]
    if "log_bytes" not in last:  # written by an older log_prompt.py: fall back to mtimes
        stale = not os.path.exists(log) or os.path.getmtime(log) < os.path.getmtime(audit)
        return f"prompts.txt has no entry for the latest prompt. {APPEND}" if stale else ""
    try:
        with open(log, "rb") as f:
            content = f.read()
    except OSError:
        return f"prompts.txt doesn't exist. Create it with the entry for the latest prompt. {APPEND}"
    size, digest = last.get("log_bytes") or 0, last.get("log_sha256")
    if digest and (len(content) < size or hashlib.sha256(content[:size]).hexdigest() != digest):
        return (
            "Earlier entries in prompts.txt changed during this turn, and it is append-only. "
            "Don't try to repair it: tell the user what changed (git diff prompts.txt), "
            "then append this turn's entry."
        )
    if len(content) > size:
        return ""
    missing = 0
    for entry in reversed(entries):
        if (entry.get("log_bytes"), entry.get("log_sha256")) != (last.get("log_bytes"), digest):
            break
        missing += 1
    if missing > 1:
        return (
            f"prompts.txt has no entry for the last {missing} prompts (an earlier turn was probably "
            f"interrupted; say so in its entry). {APPEND}"
        )
    return f"prompts.txt has no entry for the latest prompt. {APPEND}"


def main() -> int:
    try:
        data = json.load(sys.stdin)
    except ValueError:
        return 0
    if not isinstance(data, dict) or data.get("stop_hook_active"):
        return 0  # already continuing because of this hook: never loop
    if any(isinstance(t, dict) and t.get("type") in ("subagent", "workflow") for t in data.get("background_tasks") or []):
        return 0  # paused for background work; the entry is written when that work reports back
    root = os.environ.get("CLAUDE_PROJECT_DIR") or data.get("cwd") or "."
    try:
        message = problem(root, data.get("session_id"))
    except OSError:
        return 0
    if message:
        print(message, file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
