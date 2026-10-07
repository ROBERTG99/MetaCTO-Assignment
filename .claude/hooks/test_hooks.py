"""Tests for the Claude Code hooks. Run: python3 -m unittest discover -s .claude/hooks -v

Every test runs the hook as Claude Code does (JSON on stdin, CLAUDE_PROJECT_DIR set) inside
a throwaway project, so the real prompts.txt and audit file are never touched.
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest

HOOKS = os.path.dirname(os.path.abspath(__file__))
FIRST_ENTRY = "---\n[#1] 2026-10-06T10:00:00Z\nPROMPT:\nfirst\nSUMMARY:\n- ok\n"
LOG_END = "PROMPT_LOG_END"
APPEND = (
    f"cat >> prompts.txt <<'{LOG_END}'\n---\n[#2] 2026-10-07T09:00:00Z\nPROMPT:\n"
    f"Never run echo x > prompts.txt, rm prompts.txt or sed -i on it.\nSUMMARY:\n- ok\n{LOG_END}"
)

# Commands Claude really runs around the log. None of them may be blocked.
ALLOWED = [
    ("heredoc append whose body quotes destructive commands", APPEND),
    (
        "unquoted delimiter that expands $TS",
        f"TS=$(date -u +%FT%TZ)\ncat >> prompts.txt <<{LOG_END}\n[#2] $TS\n> prompts.txt\n{LOG_END}",
    ),
    (">> after the heredoc marker", f"cat <<'{LOG_END}' >> prompts.txt\n---\nbody > prompts.txt\n{LOG_END}"),
    ("<<- heredoc", f"cat >> prompts.txt <<-'{LOG_END}'\n\tline > prompts.txt\n\t{LOG_END}"),
    (
        "group appended on its last line",
        f"{{ echo '---'; cat <<'{LOG_END}'\nrm prompts.txt\n{LOG_END}\n}} >> prompts.txt",
    ),
    ("absolute-path append", f"cat >> {{root}}/prompts.txt <<'{LOG_END}'\nx\n{LOG_END}"),
    ("append after cd back", f"cd sub && ls; cd .. && cat >> prompts.txt <<'{LOG_END}'\nx\n{LOG_END}"),
    ("append from a subfolder", "cd sub && echo x >> ../prompts.txt"),
    ("echo >>", "echo x >> prompts.txt"),
    ("tee -a", "tee -a prompts.txt < other.txt"),
    ("tee --append", "tee --append prompts.txt < other.txt"),
    ("2>&1 then >>", "echo x 2>&1 >> prompts.txt"),
    ("python append", "python3 -c \"open('prompts.txt', 'a').write('x')\""),
    ("reads", "cat prompts.txt; tail -n 20 prompts.txt; grep -c '^\\[#' prompts.txt; wc -l prompts.txt"),
    ("sed -n", "sed -n '1,20p' prompts.txt"),
    ("awk read", "awk '/^\\[#/{n++} END{print n}' prompts.txt"),
    ("python read", "python3 -c \"print(len(open('prompts.audit.jsonl').readlines()))\""),
    ("python heredoc read", "python3 - <<'PY'\nfor line in open('prompts.audit.jsonl'):\n    print(line[:60])\nPY"),
    ("copy the log elsewhere", "cp prompts.txt /tmp/prompts.bak"),
    ("git add and commit", "git add prompts.txt prompts.audit.jsonl && git commit -m 'docs: log prompt 5'"),
    ("commit message naming rm", 'git commit -m "docs: rm stale note, update prompts.txt"'),
    (
        "commit message heredoc in $()",
        "git commit -m \"$(cat <<'EOF'\nchore: x\n\nrm prompts.txt and > prompts.txt are blocked\nEOF\n)\"",
    ),
    ("commit message via -F -", "git commit -F - <<'MSG'\nfix: never echo x > prompts.txt\nMSG"),
    (
        "git diff, log, show",
        "git diff prompts.txt && git log --oneline -- prompts.txt && git show HEAD:prompts.txt | tail",
    ),
    ("git stash round trip", "git stash && python3 -m pytest -q; git stash pop"),
    ("git restore --staged", "git restore --staged prompts.txt"),
    ("git branches", "git checkout -b feat/intake && git checkout main"),
    ("git restore one file", "git restore -- backend/app/main.py"),
    ("git checkout . in a subfolder", "cd sub && git checkout -- ."),
    ("write another file that mentions the log", "echo 'See prompts.txt' > docs/notes.md"),
    ("grep for a redirect string", "grep -n '> prompts.txt' CLAUDE.md"),
    ("heredoc to another file", "cat > docs/ai-development.md <<'EOF'\nThe guard blocks echo x > prompts.txt.\nEOF"),
    ("overwrite a different prompts.txt", "cat > evals/fixtures/prompts.txt <<'EOF'\nfixture\nEOF"),
    ("rm other paths", "rm -rf .pytest_cache backend/.ruff_cache && rm -f /tmp/prompts.txt"),
    ("date then tail", 'date -u +"%Y-%m-%dT%H:%M:%SZ" && tail -n 12 prompts.txt'),
    ("arithmetic shift and here-string", "echo $(( 1 << 3 )) && cat <<< 'x' > /tmp/y"),
    ("make piped to tee", "make check 2>&1 | tee /tmp/check.log"),
    ("hook tests", "python3 -m unittest discover -s .claude/hooks -v"),
    ("append to the audit", "echo '{}' >> prompts.audit.jsonl"),
    ("sort into another file", "sort prompts.txt | uniq -c > /tmp/counts.txt"),
]

# Accidents that would rewrite or lose log lines. Every one must be blocked.
BLOCKED = [
    ("overwrite", "echo x > prompts.txt"),
    ("./ prefix", "echo x > ./prompts.txt"),
    ("no spaces", "echo x>prompts.txt"),
    ("quoted target", 'printf x > "prompts.txt"'),
    ("truncate with :", ": > prompts.txt"),
    ("bare redirect", ">prompts.txt"),
    ("noclobber override", "echo x >| prompts.txt"),
    ("explicit fd", "echo x 1> prompts.txt"),
    ("&>", "make check &> prompts.txt"),
    ("heredoc overwrite", f"cat > prompts.txt <<'{LOG_END}'\nbody\n{LOG_END}"),
    ("slip on line 2", "TS=$(date -u +%FT%TZ)\nprintf '%s\\n' '---' \"[#2] $TS\" > prompts.txt"),
    ("slip on the last line", f"{{ echo '---'; cat <<'{LOG_END}'\nPROMPT:\nhi\n{LOG_END}\n}} > prompts.txt"),
    ("slip after a heredoc", f"cat >> prompts.txt <<'{LOG_END}'\nx\n{LOG_END}\nsort -u prompts.txt -o prompts.txt"),
    ("cd then ../", "cd sub && echo x > ../prompts.txt"),
    ("absolute path", "echo x > {root}/prompts.txt"),
    ("project dir variable", 'echo x > "$CLAUDE_PROJECT_DIR/prompts.txt"'),
    ("unknown folder prefix", 'echo x > "$(git rev-parse --show-toplevel)/prompts.txt"'),
    ("variable target", 'LOG=prompts.txt; echo x > "$LOG"'),
    ("tee without -a", "tee prompts.txt < other.txt"),
    ("sed -i", "sed -i '' 's/a/b/' prompts.txt"),
    ("sed -i.bak", "sed -i.bak 's/a/b/' prompts.txt"),
    ("perl -pi", "perl -pi -e 's/a/b/' prompts.txt"),
    ("awk inplace", "awk -i inplace '{print}' prompts.txt"),
    ("rewrite through a temp file", "awk 'NR>1' prompts.txt > prompts.tmp && mv prompts.tmp prompts.txt"),
    ("sort -o", "sort -o prompts.txt prompts.txt"),
    ("dd of=", "dd if=/dev/null of=prompts.txt"),
    ("cp over", "cp other.txt prompts.txt"),
    ("cp /dev/null", "cp /dev/null prompts.txt"),
    ("install over", "install -m 644 other.txt prompts.txt"),
    ("ln -sf over", "ln -sf other.txt prompts.txt"),
    ("mv away", "mv prompts.txt prompts.md"),
    ("rm", "rm -f prompts.txt"),
    ("rm by glob", "rm -f *.txt"),
    ("rm -rf the project", "rm -rf ."),
    ("truncate", "truncate -s 0 prompts.txt"),
    ("python rewrite", "python3 -c \"open('prompts.txt','w').write('')\""),
    (
        "python heredoc rewrite",
        "python3 - <<'PY'\nt = open('prompts.txt').read()\nopen('prompts.txt', 'w').write(t)\nPY",
    ),
    ("pathlib through uv run", "uv run python -c \"import pathlib; pathlib.Path('prompts.txt').write_text('')\""),
    ("bash -c", "bash -c 'echo x > prompts.txt'"),
    ("git checkout file", "git checkout -- prompts.txt"),
    ("git restore file", "git restore prompts.txt"),
    ("git checkout old version", "git checkout HEAD~1 -- prompts.txt"),
    ("git checkout .", "git checkout -- ."),
    ("git restore .", "git restore ."),
    ("git reset --hard", "git reset --hard"),
    ("git checkout -f", "git checkout -f main"),
    ("git rm --cached", "git rm --cached prompts.txt"),
    ("audit overwrite", "echo '' > prompts.audit.jsonl"),
    ("audit sed -i", "sed -i '$d' prompts.audit.jsonl"),
    ("audit temp-file rewrite", "head -n -1 prompts.audit.jsonl > a.tmp && mv a.tmp prompts.audit.jsonl"),
]


def run(hook: str, project: str, payload=None, raw=None) -> subprocess.CompletedProcess:
    env = {**os.environ, "CLAUDE_PROJECT_DIR": project}
    data = raw if raw is not None else json.dumps(payload)
    return subprocess.run(
        [sys.executable, os.path.join(HOOKS, hook)], input=data, capture_output=True, text=True, env=env, timeout=30
    )


class HookTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = os.path.realpath(self.tmp.name)
        self.log = os.path.join(self.dir, "prompts.txt")
        self.audit = os.path.join(self.dir, "prompts.audit.jsonl")
        for folder in ("sub", "docs", os.path.join("evals", "fixtures")):
            os.makedirs(os.path.join(self.dir, folder))
        self.write(self.log, FIRST_ENTRY)
        self.write(os.path.join(self.dir, "other.txt"), "other\n")
        self.write(os.path.join(self.dir, "evals", "fixtures", "prompts.txt"), "fixture\n")

    def tearDown(self) -> None:
        self.tmp.cleanup()

    @staticmethod
    def write(path: str, text: str, mode: str = "w") -> None:
        with open(path, mode, encoding="utf-8") as f:
            f.write(text)

    def read(self, path: str) -> str:
        with open(path, encoding="utf-8") as f:
            return f.read()

    def guard(self, tool: str, tool_input: dict, cwd: str = "", **extra) -> subprocess.CompletedProcess:
        payload = {"session_id": "s1", "cwd": cwd or self.dir, "hook_event_name": "PreToolUse",
                   "tool_name": tool, "tool_input": tool_input, **extra}  # fmt: skip
        return run("guard_prompt_log.py", self.dir, payload)

    def bash(self, command: str, **extra) -> subprocess.CompletedProcess:
        return self.guard("Bash", {"command": command.replace("{root}", self.dir)}, **extra)

    def submit(self, prompt: str = "p", session: str = "s1") -> subprocess.CompletedProcess:
        payload = {"session_id": session, "cwd": self.dir, "hook_event_name": "UserPromptSubmit", "prompt": prompt}
        return run("log_prompt.py", self.dir, payload)

    def stop(self, active: bool = False, session: str = "s1", background_tasks=None) -> subprocess.CompletedProcess:
        payload = {"session_id": session, "cwd": self.dir, "hook_event_name": "Stop", "stop_hook_active": active}
        if background_tasks is not None:
            payload["background_tasks"] = background_tasks
        return run("require_prompt_log.py", self.dir, payload)


class GuardTests(HookTestCase):
    def test_allows_appends_reads_and_commits(self) -> None:
        for label, command in ALLOWED:
            with self.subTest(label):
                r = self.bash(command)
                self.assertEqual(r.returncode, 0, f"{command!r} was blocked: {r.stderr}")

    def test_blocks_rewrites_anywhere_in_the_command(self) -> None:
        for label, command in BLOCKED:
            with self.subTest(label):
                r = self.bash(command)
                self.assertEqual(r.returncode, 2, f"{command!r} was allowed")
                self.assertTrue(r.stderr.startswith("Blocked:"), r.stderr)

    def test_block_message_says_how_to_append(self) -> None:
        self.assertIn(f"cat >> prompts.txt <<'{LOG_END}'", self.bash("echo x > prompts.txt").stderr)

    def test_follows_the_shell_working_directory(self) -> None:
        sub = os.path.join(self.dir, "sub")
        self.assertEqual(self.bash("echo x > prompts.txt", cwd=sub).returncode, 0)  # sub/prompts.txt
        self.assertEqual(self.bash("echo x > ../prompts.txt", cwd=sub).returncode, 2)

    def test_file_tools_on_the_log_and_the_audit(self) -> None:
        self.write(self.audit, "{}\n")
        for tool in ("Write", "Edit", "MultiEdit"):
            for path in (self.log, self.audit, "prompts.txt"):
                with self.subTest(tool=tool, path=path):
                    self.assertEqual(self.guard(tool, {"file_path": path}).returncode, 2)
        self.assertEqual(self.guard("NotebookEdit", {"notebook_path": self.log}).returncode, 2)

    def test_file_tools_on_other_files(self) -> None:
        fixture = os.path.join(self.dir, "evals", "fixtures", "prompts.txt")
        self.assertEqual(self.guard("Edit", {"file_path": fixture}).returncode, 0)
        self.assertEqual(self.guard("Write", {"file_path": os.path.join(self.dir, "README.md")}).returncode, 0)

    def test_creating_the_log_is_allowed(self) -> None:
        os.remove(self.log)
        self.assertEqual(self.guard("Write", {"file_path": self.log, "content": "x"}).returncode, 0)

    def test_subagents_cannot_write_the_log(self) -> None:
        sub = {"agent_id": "a1", "agent_type": "general-purpose"}
        self.assertEqual(self.bash(APPEND, **sub).returncode, 2)
        self.assertEqual(self.bash("tee -a prompts.txt < other.txt", **sub).returncode, 2)
        self.assertEqual(self.guard("Write", {"file_path": self.log}, **sub).returncode, 2)
        self.assertEqual(self.bash("tail -n 5 prompts.txt", **sub).returncode, 0)

    def test_never_breaks_on_bad_input(self) -> None:
        for raw in ("not json", "", "[]", json.dumps({"tool_name": "Bash", "tool_input": "x"})):
            with self.subTest(raw=raw):
                self.assertEqual(run("guard_prompt_log.py", self.dir, raw=raw).returncode, 0)
        self.assertEqual(self.bash("").returncode, 0)
        self.assertEqual(self.bash("echo 'unterminated > prompts.txt").returncode, 0)


class StopGateTests(HookTestCase):
    def append_entry(self) -> None:
        self.write(self.log, "---\n[#2] 2026-10-07T09:00:00Z\nPROMPT:\np\nSUMMARY:\n- ok\n", "a")

    def test_no_audit_yet(self) -> None:
        self.assertEqual(self.stop().returncode, 0)

    def test_blocks_until_the_entry_is_appended(self) -> None:
        self.submit()
        r = self.stop()
        self.assertEqual(r.returncode, 2)
        self.assertIn("no entry for the latest prompt", r.stderr)
        self.append_entry()
        self.assertEqual(self.stop().returncode, 0)

    def test_never_loops(self) -> None:
        self.submit()
        self.assertEqual(self.stop(active=True).returncode, 0)

    def test_touching_the_file_is_not_an_entry(self) -> None:
        self.submit()
        time.sleep(0.01)
        os.utime(self.log)  # e.g. git stash pop rewrote it: newer mtime, same content
        self.assertEqual(self.stop().returncode, 2)

    def test_detects_edits_to_earlier_entries(self) -> None:
        self.submit()
        self.write(self.log, FIRST_ENTRY.replace("first", "FIRST") + "---\n[#2] new\n")
        r = self.stop()
        self.assertEqual(r.returncode, 2)
        self.assertIn("Earlier entries in prompts.txt changed", r.stderr)

    def test_detects_a_truncated_or_missing_log(self) -> None:
        self.submit()
        self.write(self.log, "---\n")
        self.assertEqual(self.stop().returncode, 2)
        os.remove(self.log)
        self.assertEqual(self.stop().returncode, 2)

    def test_counts_prompts_from_interrupted_turns(self) -> None:
        self.submit("interrupted")
        self.submit("next")
        self.assertIn("last 2 prompts", self.stop().stderr)

    def test_ignores_prompts_from_other_sessions(self) -> None:
        self.submit(session="other")
        self.assertEqual(self.stop(session="s1").returncode, 0)
        self.assertEqual(self.stop(session="other").returncode, 2)

    def test_old_audit_lines_fall_back_to_mtimes(self) -> None:
        self.write(self.audit, json.dumps({"ts": "x", "session_id": "s1", "prompt": "p"}) + "\n")
        os.utime(self.log, (1, 1))
        self.assertEqual(self.stop().returncode, 2)
        self.append_entry()
        self.assertEqual(self.stop().returncode, 0)

    def test_waits_while_a_subagent_runs_in_the_background(self) -> None:
        self.submit()
        tasks = [{"id": "t1", "type": "subagent", "status": "running"}]
        self.assertEqual(self.stop(background_tasks=tasks).returncode, 0)

    def test_still_blocks_with_only_a_background_shell(self) -> None:
        self.submit()
        tasks = [{"id": "t2", "type": "shell", "status": "running"}]
        self.assertEqual(self.stop(background_tasks=tasks).returncode, 2)

    def test_never_breaks_on_bad_input(self) -> None:
        self.submit()
        for raw in ("not json", "", "[]"):
            with self.subTest(raw=raw):
                self.assertEqual(run("require_prompt_log.py", self.dir, raw=raw).returncode, 0)


class AuditTests(HookTestCase):
    def test_appends_the_raw_prompt_and_prints_nothing(self) -> None:
        prompt = 'Café 日本語 "quotes" $HOME `cmd`\nsecond line'
        r = self.submit(prompt)
        self.assertEqual((r.returncode, r.stdout), (0, ""))  # stdout would be added to Claude's context
        entry = json.loads(self.read(self.audit).splitlines()[-1])
        self.assertEqual(entry["prompt"], prompt)
        self.assertEqual(entry["log_bytes"], len(FIRST_ENTRY.encode()))
        self.assertRegex(entry["ts"], r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ$")

    def test_redacts_common_secret_formats(self) -> None:
        # Built at runtime so no key-shaped literal is committed (and secret scanners stay quiet).
        body = "Ab3" * 14
        secrets = [
            "sk-ant-api03-" + body,
            "sk-proj-" + body,
            "sk-" + body[:32],
            "ghp_" + body[:36],
            "github_pat_" + body[:22] + "_" + body[:30],
            "AKIA" + "IOSFODNN7" + "ABCDEFG",
            "xoxb-" + "1234567890-" + body[:24],
            "-----BEGIN RSA " + "PRIVATE KEY-----\nMIIEow\n" + body + "\n-----END RSA " + "PRIVATE KEY-----",
        ]
        mentions = "Rotate the sk-ant- key, sk-short, task-" + "Zz9" * 14 + " and the ghp_ prefix."
        prompt = "Use " + " and ".join(secrets) + " now.\n" + mentions
        self.submit(prompt)
        logged = json.loads(self.read(self.audit).splitlines()[-1])["prompt"]
        for secret in secrets:
            with self.subTest(secret=secret[:12]):
                self.assertNotIn(secret, logged)
        self.assertEqual(logged.count("[REDACTED]"), len(secrets))
        self.assertTrue(logged.startswith("Use [REDACTED] and [REDACTED]"), logged)
        self.assertTrue(logged.endswith("\n" + mentions), logged)  # prefixes and lookalikes are kept
        cut = "-----BEGIN OPENSSH " + "PRIVATE KEY-----\n" + body  # paste cut off before the END line
        self.submit("Key:\n" + cut)
        self.assertEqual(json.loads(self.read(self.audit).splitlines()[-1])["prompt"], "Key:\n[REDACTED]")

    def test_works_before_prompts_txt_exists(self) -> None:
        os.remove(self.log)
        self.submit()
        self.assertIsNone(json.loads(self.read(self.audit))["log_bytes"])

    def test_never_blocks_the_prompt(self) -> None:
        for raw in ("not json", "", "[1, 2]"):
            with self.subTest(raw=raw):
                self.assertEqual(run("log_prompt.py", self.dir, raw=raw).returncode, 0)


class FormatterTests(HookTestCase):
    def post(self, path: str) -> subprocess.CompletedProcess:
        payload = {"session_id": "s1", "cwd": self.dir, "hook_event_name": "PostToolUse", "tool_name": "Edit",
                   "tool_input": {"file_path": path}}  # fmt: skip
        return run("format_python.py", self.dir, payload)

    def ruff(self) -> str:
        """The ruff on PATH. Skips without one, or fails when HOOK_TESTS_REQUIRE_RUFF=1 is set."""
        ruff = shutil.which("ruff")
        if not ruff:
            if os.environ.get("HOOK_TESTS_REQUIRE_RUFF") == "1":
                self.fail("ruff is not on PATH and HOOK_TESTS_REQUIRE_RUFF=1")
            self.skipTest("ruff is not on PATH")
        return ruff

    def with_ruff(self) -> None:
        os.makedirs(os.path.join(self.dir, "backend", ".venv", "bin"))
        os.symlink(self.ruff(), os.path.join(self.dir, "backend", ".venv", "bin", "ruff"))

    def test_noop_without_a_project_ruff(self) -> None:
        path = os.path.join(self.dir, "a.py")
        self.write(path, "x=1\n")
        self.assertEqual(self.post(path).returncode, 0)
        self.assertEqual(self.read(path), "x=1\n")

    def test_formats_but_keeps_an_import_used_by_the_next_edit(self) -> None:
        self.with_ruff()
        path = os.path.join(self.dir, "backend", "service.py")
        self.write(path, "from datetime import datetime\nx=1\n")
        self.post(path)
        self.assertEqual(self.read(path), "from datetime import datetime\n\nx = 1\n")

    def test_uses_a_venv_at_the_project_root(self) -> None:
        os.makedirs(os.path.join(self.dir, ".venv", "bin"))
        os.symlink(self.ruff(), os.path.join(self.dir, ".venv", "bin", "ruff"))
        path = os.path.join(self.dir, "pkg", "mod.py")
        os.makedirs(os.path.dirname(path))
        self.write(path, "import os\ny=2\n")
        self.post(path)
        self.assertEqual(self.read(path), "import os\n\ny = 2\n")

    def test_leaves_files_outside_the_project_alone(self) -> None:
        self.with_ruff()
        with tempfile.TemporaryDirectory() as outside:
            path = os.path.join(outside, "x.py")
            self.write(path, "x=1\n")
            self.post(path)
            self.assertEqual(self.read(path), "x=1\n")


if __name__ == "__main__":
    unittest.main()
