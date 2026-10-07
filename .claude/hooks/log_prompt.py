#!/usr/bin/env python3
"""UserPromptSubmit hook: append every raw prompt to prompts.audit.jsonl.

Deterministic audit trail that backs up the prompts.txt rule in CLAUDE.md (CLAUDE.md is
guidance the model follows; a hook always runs). Each line also records the size and
SHA-256 of prompts.txt when the prompt arrived, so require_prompt_log.py can check at the
end of the turn that an entry was appended and that nothing before it changed.
Prints nothing on stdout: on this event, stdout would be added to Claude's context.
"""

import hashlib
import json
import os
import sys
from datetime import datetime, timezone


def main() -> int:
    try:
        data = json.load(sys.stdin)
    except ValueError:
        return 0  # never block the user's prompt because of the audit hook
    if not isinstance(data, dict):
        return 0
    root = os.environ.get("CLAUDE_PROJECT_DIR") or data.get("cwd") or "."
    try:
        with open(os.path.join(root, "prompts.txt"), "rb") as f:
            log = f.read()
        size, digest = len(log), hashlib.sha256(log).hexdigest()
    except OSError:
        size, digest = None, None
    entry = {
        "ts": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "session_id": data.get("session_id"),
        "prompt": data.get("prompt", ""),
        "log_bytes": size,
        "log_sha256": digest,
    }
    try:
        with open(os.path.join(root, "prompts.audit.jsonl"), "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except OSError as e:
        print(f"log_prompt.py could not write prompts.audit.jsonl: {e}", file=sys.stderr)
        return 1  # non-blocking: the prompt goes through and the user sees the notice
    return 0


if __name__ == "__main__":
    sys.exit(main())
