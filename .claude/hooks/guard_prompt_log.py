#!/usr/bin/env python3
"""PreToolUse hook: keep prompts.txt and prompts.audit.jsonl append-only.

Appending is allowed (`cat >> prompts.txt <<'PROMPT_LOG_END'`, `>>`, `tee -a`). Anything
that would overwrite, truncate, edit, move, delete or restore either file is blocked with
exit code 2, and the message on stderr tells Claude how to append instead.

File tools are checked by resolved path, so evals/fixtures/prompts.txt is not the log.
Bash commands are read the way a shell reads them: heredoc bodies are skipped (a logged
prompt may quote `> prompts.txt`), every other line is checked, quotes and $(...) are
understood, and `cd` is followed. So `cd backend && cat > ../prompts.txt` is caught and
`git commit -m "rm prompts.txt"` is not. Scripts passed to python, node, perl or bash
(-c, -e or a heredoc) are scanned for writes to the two files.

It guards against accidents, not against a determined adversary. require_prompt_log.py
checks the effect at the end of every turn: the log must only have grown.
"""

import glob
import json
import os
import re
import sys

LOG, AUDIT = "prompts.txt", "prompts.audit.jsonl"
HOW_TO = "Append instead: cat >> prompts.txt <<'PROMPT_LOG_END' ... PROMPT_LOG_END (CLAUDE.md, Prompt Logging)."
DISCARD = (
    "Blocked: `{cmd}` would also throw away the uncommitted lines in prompts.txt and "
    "prompts.audit.jsonl, which are append-only. Restore only the files you mean, "
    "for example: git restore -- path/to/file"
)
UNKNOWN = "\x00"  # stands for text the hook can't know: unset variables, command output
GLOB_CHARS = "*?["
RESERVED = {"!", "{", "}", "then", "else", "elif", "do", "if", "while", "until", "fi", "done", "esac"}
SKIP_COMMANDS = {"for", "case", "select", "function", "in"}
INTERPRETERS = {"python", "python3", "node", "ruby", "perl", "bun", "deno"}
SHELLS = {"bash", "sh", "zsh", "dash"}


class Blocked(Exception):
    pass


# ---------------------------------------------------------------- lexer
class Word:
    def __init__(self) -> None:
        self.parts: list = []  # (kind, value); kind: lit, qlit, var, glob, tilde, unknown
        self.subs: list = []  # token lists of $(...), `...`, <(...) inside the word

    def add(self, kind: str, value: str = "") -> None:
        self.parts.append((kind, value))

    def literal(self) -> str:
        return "".join(v for k, v in self.parts if k in ("lit", "qlit", "glob"))


class Heredoc:
    def __init__(self, strip_tabs: bool) -> None:
        self.strip_tabs = strip_tabs
        self.delim = None
        self.body = ""


class Lexer:
    """Turns a command string into tokens: ("word", Word), ("op", str), ("redir", op, Heredoc|None, Word)."""

    def __init__(self, src: str) -> None:
        self.s, self.n = src, len(src)
        self.pending: list = []  # heredocs whose body starts after the next newline

    def lex(self, i: int = 0, closer: str = "") -> tuple:
        s, n = self.s, self.n
        toks: list = []
        word = None
        depth = 0

        def end_word() -> None:
            nonlocal word
            if word is None:
                return
            last = toks[-1] if toks else None
            if last and last[0] == "redir" and last[3] is None:
                if isinstance(last[2], Heredoc):
                    last[2].delim = word.literal()
                    self.pending.append(last[2])
                toks[-1] = (last[0], last[1], last[2], word)
            else:
                toks.append(("word", word))
            word = None

        while i < n:
            c = s[i]
            if c in " \t":
                end_word()
                i += 1
            elif c == "\n":
                end_word()
                toks.append(("op", "\n"))
                i = self.read_heredoc_bodies(i + 1)
            elif c == "#" and word is None:
                while i < n and s[i] != "\n":
                    i += 1
            elif c == "\\":
                if i + 1 < n and s[i + 1] == "\n":
                    i += 2
                else:
                    word = word or Word()
                    word.add("qlit", s[i + 1 : i + 2])
                    i += 2
            elif c == "'":
                j = s.find("'", i + 1)
                j = n if j < 0 else j
                word = word or Word()
                word.add("qlit", s[i + 1 : j])
                i = j + 1
            elif c == '"':
                word = word or Word()
                i = self.double_quoted(i + 1, word)
            elif c == "$":
                word = word or Word()
                i = self.dollar(i, word, quoted=False)
            elif c == "`":
                word = word or Word()
                i = self.backtick(i, word)
            elif c in "<>" or (c == "&" and s[i + 1 : i + 2] == ">"):
                if c in "<>" and s[i + 1 : i + 2] == "(":  # process substitution
                    word = word or Word()
                    sub, i = self.lex(i + 2, ")")
                    word.subs.append(sub)
                    word.add("unknown", UNKNOWN)
                    continue
                if word is not None and all(k == "lit" for k, _ in word.parts) and word.literal().isdigit():
                    word = None  # a file descriptor number such as the 2 in 2>
                end_word()
                op = next(
                    o
                    for o in ("&>>", "&>", "<<<", "<<-", "<<", "<>", "<&", "<", ">>", ">|", ">&", ">")
                    if s.startswith(o, i)
                )
                i += len(op)
                target = Heredoc(op == "<<-") if op in ("<<", "<<-") else None
                toks.append(("redir", op, target, None))
            elif c in ";|&":
                end_word()
                op = next(o for o in ("&&", "||", ";;", "|&", ";", "|", "&") if s.startswith(o, i))
                toks.append(("op", op))
                i += len(op)
            elif c == "(":
                end_word()
                depth += 1
                toks.append(("op", "("))
                i += 1
            elif c == ")":
                end_word()
                if closer == ")" and depth == 0:
                    return toks, i + 1
                depth -= 1
                toks.append(("op", ")"))
                i += 1
            else:
                word = word or Word()
                if c in GLOB_CHARS:
                    word.add("glob", c)
                elif c == "~" and not word.parts:
                    word.add("tilde", c)
                else:
                    word.add("lit", c)
                i += 1
        end_word()
        return toks, i

    def read_heredoc_bodies(self, i: int) -> int:
        for doc in self.pending:
            lines = []
            while i < self.n:
                j = self.s.find("\n", i)
                j = self.n if j < 0 else j
                line = self.s[i:j]
                i = j + 1
                if (line.lstrip("\t") if doc.strip_tabs else line) == doc.delim:
                    break
                lines.append(line)
            doc.body = "\n".join(lines)
        self.pending = []
        return i

    def double_quoted(self, i: int, word: Word) -> int:
        s, n = self.s, self.n
        while i < n and s[i] != '"':
            c = s[i]
            if c == "\\" and i + 1 < n:
                word.add("qlit", s[i + 1] if s[i + 1] in '$`"\\' else s[i : i + 2])
                i += 2
            elif c == "$":
                i = self.dollar(i, word, quoted=True)
            elif c == "`":
                i = self.backtick(i, word)
            else:
                word.add("qlit", c)
                i += 1
        return i + 1

    def dollar(self, i: int, word: Word, quoted: bool) -> int:
        s, n = self.s, self.n
        nxt = s[i + 1 : i + 2]
        if s.startswith("$((", i):
            depth, i = 2, i + 3
            while i < n and depth:
                depth += {"(": 1, ")": -1}.get(s[i], 0)
                i += 1
            word.add("unknown", UNKNOWN)
            return i
        if nxt == "(":
            sub, i = self.lex(i + 2, ")")
            word.subs.append(sub)
            word.add("unknown", UNKNOWN)
            return i
        if nxt == "{":
            j = s.find("}", i)
            j = n if j < 0 else j
            name = s[i + 2 : j]
            word.add("var", name) if re.fullmatch(r"[A-Za-z_]\w*", name) else word.add("unknown", UNKNOWN)
            return j + 1
        if nxt == "'" and not quoted:
            j = i + 2
            while j < n and s[j] != "'":
                j += 2 if s[j] == "\\" else 1
            word.add("qlit", s[i + 2 : j])
            return j + 1
        m = re.compile(r"[A-Za-z_]\w*").match(s, i + 1)
        if m:
            word.add("var", m.group())
            return m.end()
        if nxt and nxt in "?#@*$!-0123456789":
            word.add("unknown", UNKNOWN)
            return i + 2
        word.add("qlit" if quoted else "lit", "$")
        return i + 1

    def backtick(self, i: int, word: Word) -> int:
        j = i + 1
        while j < self.n and self.s[j] != "`":
            j += 2 if self.s[j] == "\\" else 1
        word.subs.append(Lexer(self.s[i + 1 : j]).lex()[0])
        word.add("unknown", UNKNOWN)
        return j + 1


# ---------------------------------------------------------------- checker
class Checker:
    def __init__(self, root: str, cwd: str, in_subagent: bool) -> None:
        self.root = os.path.realpath(root)
        self.protected = {os.path.join(self.root, LOG): LOG, os.path.join(self.root, AUDIT): AUDIT}
        self.in_subagent = in_subagent
        self.cwd = os.path.realpath(cwd) if cwd else self.root
        self.env = {"HOME": os.path.expanduser("~"), "CLAUDE_PROJECT_DIR": self.root}

    # ---- paths
    def expand(self, word: Word) -> list:
        out, has_glob = [], False
        for kind, value in word.parts:
            if kind == "var":
                value = self.cwd if value == "PWD" and self.cwd else self.env.get(value, UNKNOWN)
            elif kind == "tilde":
                value = self.env["HOME"]
            elif kind == "glob":
                has_glob = True
            out.append(value)
        text = "".join(out)
        if has_glob and UNKNOWN not in text and self.cwd:
            matches = glob.glob(text if os.path.isabs(text) else os.path.join(self.cwd, text))
            if matches:
                return matches
        return [text]

    def resolve(self, value: str):
        if not value or UNKNOWN in value:
            return None
        if os.path.isabs(value):
            return os.path.realpath(value)
        if self.cwd is None:  # after a cd we couldn't follow: fall back to the bare name
            return os.path.join(self.root, value) if value in self.protected.values() else None
        return os.path.realpath(os.path.join(self.cwd, value))

    def target(self, value: str):
        if UNKNOWN in value:  # "$(git rev-parse --show-toplevel)/prompts.txt" and the like
            head, _, base = value.rpartition("/")
            return base if head and base in (LOG, AUDIT) else None
        return self.protected.get(self.resolve(value) or "")

    def contains_protected(self, value: str) -> bool:
        path = self.resolve(value)
        return bool(path) and any(p.startswith(os.path.join(path, "")) for p in self.protected)

    def block(self, name: str, action: str, detail: str = "") -> None:
        if name == AUDIT:
            raise Blocked(
                f"Blocked: this would {action} prompts.audit.jsonl. It is the audit trail that "
                f"log_prompt.py appends to on every prompt; leave it as it is.{detail}"
            )
        raise Blocked(f"Blocked: this would {action} prompts.txt, which is append-only.{detail} {HOW_TO}")

    def hit(self, value: str, action: str) -> None:
        name = self.target(value)
        if name:
            self.block(name, action)

    def appending(self, value: str) -> None:
        if self.in_subagent and self.target(value) == LOG:
            raise Blocked(
                "Blocked: only the main conversation writes prompts.txt. "
                "Report what you did in your final message instead."
            )

    # ---- commands
    def run(self, toks: list) -> None:
        stack, cmd = [], []
        for tok in toks + [("op", ";")]:
            if tok[0] == "op":
                self.simple(cmd)
                cmd = []
                if tok[1] == "(":
                    stack.append((self.cwd, dict(self.env)))
                elif tok[1] == ")" and stack:
                    self.cwd, self.env = stack.pop()
            else:
                cmd.append(tok)

    def run_sub(self, toks: list) -> None:
        saved = (self.cwd, dict(self.env))
        try:
            self.run(toks)
        finally:
            self.cwd, self.env = saved

    def simple(self, toks: list) -> None:
        words = [t[1] for t in toks if t[0] == "word"]
        redirs = [t for t in toks if t[0] == "redir"]
        for w in words + [r[3] for r in redirs if r[3] is not None]:
            for sub in w.subs:
                self.run_sub(sub)
        heredoc_bodies = [r[2].body for r in redirs if isinstance(r[2], Heredoc)]
        for _, op, _, target in redirs:
            if target is None or op in ("<<", "<<-", "<<<", "<", "<&"):
                continue
            for value in self.expand(target):
                if op in (">>", "&>>"):
                    self.appending(value)
                elif not (op == ">&" and (value.isdigit() or value == "-")):
                    self.hit(value, "overwrite")
        argv: list = []
        assignments = []
        for w in words:
            lit = w.literal() if not argv else ""
            if not argv and re.fullmatch(r"[A-Za-z_]\w*=.*", lit or "", re.DOTALL) and w.parts[0][0] != "qlit":
                assignments.append(w)
                continue
            argv.extend(self.expand(w))
        while argv and argv[0] in RESERVED:
            argv.pop(0)
        if not argv:
            for w in assignments:  # NAME=value on its own sets a shell variable
                name, _, value = "".join(self.expand(w)).partition("=")
                self.env[name] = value
            return
        if argv[0] in SKIP_COMMANDS:
            return
        self.command(argv, heredoc_bodies)

    def command(self, argv: list, bodies: list) -> None:
        argv = strip_wrappers(argv)
        if not argv:
            return
        name, args = os.path.basename(argv[0]), argv[1:]
        files = operands(args)
        if name in ("export", "local", "declare", "readonly", "typeset"):
            for a in args:
                key, eq, value = a.partition("=")
                if eq and re.fullmatch(r"[A-Za-z_]\w*", key):
                    self.env[key] = value
        elif name in ("cd", "pushd"):
            dest = files[-1] if files else self.env["HOME"]
            self.cwd = self.resolve(dest) if dest != "-" else None
        elif name == "popd":
            self.cwd = None
        elif name in ("rm", "unlink", "shred", "truncate", "srm"):
            recursive = name == "rm" and (has_flag(args, "rR") or "--recursive" in args)
            for f in files:
                self.hit(f, "delete or truncate")
                if recursive and self.contains_protected(f):
                    raise Blocked(
                        f"Blocked: `rm -r {f}` would delete prompts.txt and prompts.audit.jsonl. "
                        "Remove only the paths you mean."
                    )
        elif name == "mv":
            for f in files:
                self.hit(f, "move or replace")
        elif (
            name in ("cp", "install", "ln", "rsync")
            and len(files) >= 2
            and not has_flag(args, "t")
            and not any(a.startswith("--target-directory") for a in args)
        ):
            self.hit(files[-1], "replace")
        elif name == "dd":
            if not ("oflag=append" in args and "conv=notrunc" in args):
                for a in args:
                    if a.startswith("of="):
                        self.hit(a[3:], "overwrite")
        elif name == "tee":
            append = "--append" in args or has_flag(args, "a")
            for f in files:
                self.appending(f) if append else self.hit(f, "overwrite")
        elif edits_in_place(name, args):
            for f in files:
                self.hit(f, "edit")
        elif name == "sort":
            for i, a in enumerate(args):
                if a in ("-o", "--output") and i + 1 < len(args):
                    self.hit(args[i + 1], "overwrite")
                elif a.startswith("--output="):
                    self.hit(a.split("=", 1)[1], "overwrite")
                elif a.startswith("-o") and len(a) > 2 and not a.startswith("--"):
                    self.hit(a[2:], "overwrite")
        elif name == "git":
            self.git(args)
        if name in SHELLS or name == "eval":
            code = " ".join(args) if name == "eval" else option_value(args, "-c")
            for script in [code] if code is not None else bodies if not files else []:
                self.run_sub(Lexer(script).lex()[0])
        elif name.rstrip("0123456789.") in INTERPRETERS:
            code = option_value(args, "-c") or option_value(args, "-e")
            for script in [code] if code is not None else bodies if not files or files == ["-"] else []:
                self.scan_code(script)

    def git(self, args: list) -> None:
        saved = self.cwd
        try:
            self.git_subcommand(args)
        finally:
            self.cwd = saved

    def git_subcommand(self, args: list) -> None:
        i = 0
        while i < len(args) and args[i].startswith("-"):
            if args[i] == "-C" and i + 1 < len(args):
                self.cwd = self.resolve(args[i + 1])
                i += 1
            elif args[i] in ("-c", "--git-dir", "--work-tree"):
                i += 1
            i += 1
        if i >= len(args):
            return
        sub, rest = args[i], args[i + 1 :]
        paths = rest[rest.index("--") + 1 :] if "--" in rest else operands(rest)
        if sub in ("checkout", "restore"):
            if sub == "restore" and ("--staged" in rest or "-S" in rest) and not ("--worktree" in rest or "-W" in rest):
                return  # only unstages; the file on disk is untouched
            if sub == "checkout" and ("-f" in rest or "--force" in rest):
                raise Blocked(DISCARD.format(cmd="git checkout -f"))
            for p in paths:
                self.hit(p, "restore an old version of")
                if p in (":/", ":/*", "*", ":(top)") or self.contains_protected(p):
                    raise Blocked(DISCARD.format(cmd=f"git {sub} {p}"))
        elif sub in ("rm", "mv"):
            for p in operands(rest):
                self.hit(p, "remove or untrack")
        elif sub == "reset" and "--hard" in rest:
            raise Blocked(DISCARD.format(cmd="git reset --hard"))

    def scan_code(self, code: str) -> None:
        for pattern, action in CODE_WRITES:
            for m in pattern.finditer(code):
                mode = m.groupdict().get("mode")
                if mode is not None and not re.search(r"[wx+]", mode):
                    if "a" in mode:
                        self.appending(m.group("path"))
                    continue
                self.hit(m.group("path"), action)


Q = r"""(['"])(?P<path>[^'"\n]+)\1"""
CODE_WRITES = [
    (re.compile(r"\bopen\(\s*[rfb]?" + Q + r"\s*,\s*(?:mode\s*=\s*)?(['\"])(?P<mode>[^'\"]*)\3"), "overwrite"),
    (
        re.compile(r"\bPath\(\s*" + Q + r"\s*\)\s*\.\s*(?:write_text|write_bytes|unlink|rename|replace)\b"),
        "overwrite or delete",
    ),
    (re.compile(r"\bPath\(\s*" + Q + r"\s*\)\s*\.\s*open\(\s*(?:mode\s*=\s*)?(['\"])(?P<mode>[^'\"]*)\3"), "overwrite"),
    (
        re.compile(
            r"\b(?:os\.(?:remove|unlink|truncate|rename|replace)|shutil\.move|fs\.(?:writeFileSync|writeFile|unlinkSync|unlink|rmSync|truncateSync|renameSync)|File\.(?:write|delete))\(\s*"
            + Q
        ),
        "overwrite or delete",
    ),
    (
        re.compile(
            r"\b(?:shutil\.(?:copy|copy2|copyfile|move)|os\.(?:rename|replace)|fs\.(?:copyFileSync|renameSync))\(\s*[^,()]+,\s*"
            + Q
        ),
        "replace",
    ),
    (re.compile(r"\bopen\s*\(?\s*[^,;]+,\s*['\"](?:>|\+<|\+>)['\"]\s*,\s*" + Q), "overwrite"),  # perl 3-arg open
]


# ---------------------------------------------------------------- helpers
def strip_wrappers(argv: list) -> list:
    while argv:
        head = os.path.basename(argv[0])
        if head in ("sudo", "command", "builtin", "nohup", "time", "exec", "xargs", "stdbuf", "nice", "env", "timeout"):
            argv = argv[1:]
            while argv and (
                argv[0].startswith("-")
                or re.fullmatch(r"[A-Za-z_]\w*=.*", argv[0], re.DOTALL)
                or (head == "timeout" and re.fullmatch(r"[\d.]+[smhd]?", argv[0]))
            ):
                takes_value = argv[0] in ("-n", "-u", "-s", "-k", "-g")
                argv = argv[2:] if takes_value else argv[1:]
        elif head in ("uv", "poetry", "pipenv") and argv[1:2] == ["run"]:
            argv = argv[2:]
            while argv and argv[0].startswith("-"):
                argv = argv[1:]
        else:
            return argv
    return argv


def edits_in_place(name: str, args: list) -> bool:
    if name in ("sed", "gsed"):
        return has_flag(args, "i") or any(a.startswith("--in-place") for a in args)
    if name in ("perl", "ruby"):
        return has_flag(args, "i")
    if name in ("awk", "gawk"):
        return "inplace" in args or "-iinplace" in args or "--include=inplace" in args
    return name in ("ed", "ex")


def operands(args: list) -> list:
    out, after_dashdash = [], False
    for a in args:
        if after_dashdash or not a.startswith("-") or a == "-":
            out.append(a)
        elif a == "--":
            after_dashdash = True
    return out


def has_flag(args: list, letters: str) -> bool:
    for a in args:
        if a == "--":
            break
        if a.startswith("-") and not a.startswith("--") and len(a) > 1:
            cluster = re.match(r"-[A-Za-z]+", a)
            if cluster and any(ch in cluster.group()[1:] for ch in letters):
                return True
    return False


def option_value(args: list, flag: str):
    for i, a in enumerate(args):
        if a == flag and i + 1 < len(args):
            return args[i + 1]
        if a.startswith("-") and not a.startswith("--") and a.endswith(flag[1]) and i + 1 < len(args) and len(a) <= 4:
            return args[i + 1]  # clusters such as -pe, -ne
    return None


# ---------------------------------------------------------------- entry point
def check(data: dict) -> None:
    root = os.environ.get("CLAUDE_PROJECT_DIR") or data.get("cwd") or os.getcwd()
    checker = Checker(root, data.get("cwd") or root, bool(data.get("agent_id")))
    tool = data.get("tool_name", "")
    tool_input = data.get("tool_input") or {}
    if not isinstance(tool_input, dict):
        return
    if tool in ("Write", "Edit", "MultiEdit", "NotebookEdit"):
        path = tool_input.get("file_path") or tool_input.get("notebook_path") or ""
        name = checker.target(path)
        if name and os.path.exists(checker.resolve(path)):
            checker.block(name, "rewrite")
        if name == LOG and checker.in_subagent:
            checker.appending(path)
    elif tool == "Bash":
        checker.run(Lexer(tool_input.get("command") or "").lex()[0])


def main() -> int:
    try:
        data = json.load(sys.stdin)
        if isinstance(data, dict):
            check(data)
    except Blocked as e:
        print(e, file=sys.stderr)
        return 2
    except Exception:
        return 0  # never break Claude Code because of a bug in this hook; the Stop gate still checks the effect
    return 0


if __name__ == "__main__":
    sys.exit(main())
