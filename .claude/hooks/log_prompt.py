#!/usr/bin/env python3
"""UserPromptSubmit hook: append every raw prompt to prompts.audit.jsonl.

Deterministic audit trail that backs up the prompts.txt rule in CLAUDE.md (CLAUDE.md is
guidance the model follows; a hook always runs). Each line also records the size and
SHA-256 of prompts.txt when the prompt arrived, so require_prompt_log.py can check at the
end of the turn that an entry was appended and that nothing before it changed.
The audit file is committed, so common API key, token and private key formats in the prompt
are replaced with [REDACTED] before it is written.
Prints nothing on stdout: on this event, stdout would be added to Claude's context.
"""

import hashlib
import json
import os
import re
import sys
from datetime import datetime, timezone

# Each pattern needs a real body after the prefix, so a prompt that only names a format
# ("the sk-ant- key", "a ghp_ token") is kept as written.
SECRET = re.compile(
    r"\bsk-ant-[A-Za-z0-9_-]{20,}"  # Anthropic
    r"|\bsk-[A-Za-z0-9_-]{32,}"  # OpenAI and other sk- keys
    r"|\bghp_[A-Za-z0-9]{36,}|\bgithub_pat_[A-Za-z0-9_]{40,}"  # GitHub
    r"|\bAKIA[0-9A-Z]{16}\b"  # AWS access key ID
    r"|\bxox[a-z]-[A-Za-z0-9-]{10,}"  # Slack
    r"|-----BEGIN [A-Z ]*PRIVATE KEY-----(?:.*?-----END [A-Z ]*PRIVATE KEY-----|.*)",  # no END: to the end
    re.DOTALL,
)


def redact(text: str) -> str:
    return SECRET.sub("[REDACTED]", text)


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
        "prompt": redact(str(data.get("prompt") or "")),
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
