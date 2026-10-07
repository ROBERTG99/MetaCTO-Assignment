#!/usr/bin/env python3
"""PostToolUse hook: format and lint-fix a Python file right after Claude edits it.

Uses the ruff installed in the nearest virtual environment above the edited file
(<dir>/.venv/bin/ruff, searched up to the project root), so the version matches the one the
project pins. Works for a single-package repo or a monorepo (backend/.venv, services/x/.venv).
Does nothing if no such ruff exists, only touches files inside the project, and never blocks. Unused imports (F401) are not auto-removed: Claude often adds an import
in one edit and its first use in the next, and removing it in between breaks the second edit.
"""

import contextlib
import json
import os
import subprocess
import sys


def main() -> None:
    try:
        data = json.load(sys.stdin)
    except ValueError:
        return
    if not isinstance(data, dict):
        return
    path = (data.get("tool_input") or {}).get("file_path", "")
    if not isinstance(path, str) or not path.endswith(".py"):
        return
    root = os.path.realpath(os.environ.get("CLAUDE_PROJECT_DIR") or data.get("cwd") or ".")
    path = os.path.realpath(path if os.path.isabs(path) else os.path.join(root, path))
    if not (path.startswith(root + os.sep) and os.path.exists(path)):
        return
    package = find_package(os.path.dirname(path), root)
    if package is None:
        return
    ruff = os.path.join(package, ".venv", "bin", "ruff")
    for args in (["check", "--fix", "--unfixable", "F401", "--quiet", path], ["format", "--quiet", path]):
        subprocess.run([ruff, *args], cwd=package, capture_output=True, timeout=30)


def find_package(start: str, root: str):
    """The closest directory from start up to root that has .venv/bin/ruff, or None."""
    current = start
    while current.startswith(root):
        if os.path.exists(os.path.join(current, ".venv", "bin", "ruff")):
            return current
        if current == root:
            return None
        current = os.path.dirname(current)
    return None


if __name__ == "__main__":
    with contextlib.suppress(Exception):  # a formatter problem must never block Claude
        main()
    sys.exit(0)
