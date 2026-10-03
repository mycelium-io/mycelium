# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""Check the ``mycelium`` commands written in prose against the CLI itself.

Agents learn the CLI from what they are shown: the skill, their notes brief,
the wake prompts, the docs. A command written there that the CLI no longer
takes (a flag renamed, a subcommand moved) teaches every agent that reads it to
type something that fails. So every command written in prose is parsed against
the commands Typer builds:

- in markdown (the docs, the skills, the READMEs): code spans and code blocks;
- in Python (prompts, briefs, the hub's wake digest): string literals, with an
  f-string's ``{placeholders}`` read as values;
- in the frontend's TypeScript: string literals that start with a command.

A placeholder (``<id>``, ``{room}``, ``...``) stands for a value. A command the
CLI does not have is only reported where the text is plainly code, so prose
that merely mentions Mycelium is left alone; a flag the command does not take
is reported wherever the command is recognised.

    uv run python -m mycelium.cli_prose        # from mycelium-cli/, scans the repo

``tests/test_cli_prose.py`` runs it over the repository.
"""

from __future__ import annotations

import ast
import re
import shlex
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

#: Where prose that teaches the CLI lives, relative to the repository root.
SOURCES = (
    "README.md",
    "CLAUDE.md",
    "mycelium-cli/src/mycelium/docs/**/*.md",
    "mycelium-cli/src/mycelium/skills/**/*.md",
    "mycelium-cli/src/mycelium/**/*.py",
    "fastapi-backend/app/**/*.py",
    "mycelium-frontend/src/**/*.ts",
    "mycelium-frontend/src/**/*.tsx",
    ".claude/skills/**/*.md",
    "mycelium-promo/README.md",
)

#: Commands written on purpose in a shape the CLI does not take, with why.
#: Keyed by (path relative to the root, the command as written).
EXEMPT: dict[tuple[str, str], str] = {}

#: Whole files known to be out of date, waiting on a rewrite, with where that
#: is tracked. A listed file that checks clean is reported, so this shrinks.
STALE: dict[str, str] = {}

_PLACEHOLDER = re.compile(r"^(<.*>|\{.*\}|\.\.\.|…|\$.*|\[.*\]|\".*\"|'.*')$")


@dataclass(frozen=True)
class Finding:
    path: str
    line: int
    command: str
    problem: str

    def __str__(self) -> str:
        return f"{self.path}:{self.line}: `{self.command}`: {self.problem}"


# ── the CLI as a tree ────────────────────────────────────────────────────────


@dataclass
class Node:
    name: str
    children: dict[str, Node]
    flags: dict[str, bool]  # flag -> takes a value
    #: A group that also takes words of its own (``docs <topic>``), so a word
    #: that names no subcommand is one of those, not a mistake.
    takes_words: bool = False


def tree() -> Node:
    """Every command Typer builds, with the flags each takes."""
    import typer.main

    from mycelium.cli import app

    def node(name: str, cmd: Any) -> Node:
        flags: dict[str, bool] = {"--help": False, "-h": False}
        for p in getattr(cmd, "params", []):
            takes_value = not getattr(p, "is_flag", False) and not getattr(p, "count", False)
            for opt in [*getattr(p, "opts", []), *getattr(p, "secondary_opts", [])]:
                if opt.startswith("-"):
                    flags[opt] = takes_value
        children = {n: node(n, c) for n, c in getattr(cmd, "commands", {}).items()}
        words = any(
            getattr(p, "param_type_name", "") == "argument" for p in getattr(cmd, "params", [])
        )
        return Node(name, children, flags, takes_words=words)

    return node("mycelium", typer.main.get_command(app))


# ── checking one command ─────────────────────────────────────────────────────


def _tokens(command: str) -> list[str]:
    """Words, with a quoted one kept quoted: `"--all"` is text, not a flag."""
    try:
        return shlex.split(command, posix=False)
    except ValueError:  # an unbalanced quote: a cut-off example
        return command.split()


def check(command: str, root: Node, *, code: bool) -> str | None:
    """What is wrong with ``command`` (``mycelium …``), or None.

    ``code`` says the text is plainly a command (a code span or block), so a
    subcommand the CLI lacks is worth reporting; in looser text it is not.
    """
    words = [w.strip("[](),;|") for w in _tokens(command)][1:]
    here = root
    i = 0
    # Walk subcommands while the words name them.
    while i < len(words) and here.children:
        word = words[i]
        if word in here.children:
            here = here.children[word]
            i += 1
            continue
        if word.startswith("-") or _PLACEHOLDER.match(word) or not word or here.takes_words:
            break
        if not code:
            return None  # prose that mentions Mycelium, not a command
        if not re.fullmatch(r"[a-z][a-z0-9-]*", word):
            break
        path = " ".join(["mycelium", *words[:i]])
        return f"{path} has no command {word!r}"
    if here is root:
        return None
    # The rest: flags this command must take; positionals are anyone's.
    global_flags = root.flags
    while i < len(words):
        word = words[i]
        i += 1
        if not word.startswith("-") or word in {"-", "--"} or re.fullmatch(r"-\d.*", word):
            continue
        flag = word.split("=", 1)[0]
        if flag in here.flags:
            if here.flags[flag] and "=" not in word:
                i += 1  # its value
            continue
        if flag in global_flags:
            continue
        return f"{' '.join(['mycelium', *_path_of(root, here)])} takes no {flag}"
    return None


def _path_of(root: Node, target: Node) -> list[str]:
    def walk(node: Node, path: list[str]) -> list[str] | None:
        if node is target:
            return path
        for name, child in node.children.items():
            found = walk(child, [*path, name])
            if found is not None:
                return found
        return None

    return walk(root, []) or []


# ── finding commands in text ─────────────────────────────────────────────────

_IN_CODE = re.compile(r"`([^`\n]*\bmycelium [^`\n]*)`|<code>(.*?\bmycelium .*?)</code>")
_COMMAND = re.compile(r"(?<![\w./-])mycelium (?:(?!</)[^`\"'\n#)]|\"[^\"\n]*\"|'[^'\n]*')+")
#: Rich markup (`[bold]`, `[/dim]`) a string carries for the terminal.
_MARKUP = re.compile(r"\[/?[a-z ]+\]")
#: Where a command ends: two spaces, a comment, an arrow, or the shell
#: joining it to another (a pipe, `&&`, `;`, a redirect).
_END = re.compile(r"\s{2,}|\s+#\s|\s+→|\s+\(|;(?:\s|$)|\s+(?:\|\|?|&&|\d?>>?|<)(?=[\s&]|$)")


#: What may come right before a command in a shell line: nothing, a prompt, a
#: shell operator, a runner (`uv run`), or an environment assignment.
_LEADS = re.compile(
    r"(^|\$|&&|\|\||;|\||\(|`|!|\b(?:uv run|exec|sudo|npx|then|do|if|while|until)|\S+=\S*)\s*$"
)


def _commands_in(text: str, *, shell: bool = False) -> list[str]:
    """Each ``mycelium …`` command in a run of text, cut where it ends.

    In a shell line (``shell``) only a command in command position counts, and
    a comment is not read: ``echo "mycelium skill present"`` runs echo.
    """
    text = _MARKUP.sub("", text)
    if shell:
        text = re.split(r"(?:^|\s)#\s", text)[0]
    out = []
    for m in _COMMAND.finditer(text):
        if shell and not _LEADS.search(text[: m.start()]):
            continue
        out.append(_END.split(m.group(0))[0].rstrip(" .,:;"))
    return out


def _code_spans(text: str) -> list[str]:
    return [a or b for a, b in _IN_CODE.findall(text)]


def from_markdown(text: str) -> list[tuple[int, str, bool]]:
    """(line, command, is code) for every command in a markdown document."""
    out: list[tuple[int, str, bool]] = []
    fence = False
    for n, line in enumerate(text.splitlines(), 1):
        if line.lstrip().startswith(("```", "~~~")):
            fence = not fence
            continue
        if fence:
            out.extend((n, c, True) for c in _commands_in(line, shell=True))
            continue
        for span in _code_spans(line):
            out.extend((n, c, True) for c in _commands_in(span))
    return out


def _string_value(node: ast.AST) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.JoinedStr):
        parts = []
        for v in node.values:
            if isinstance(v, ast.Constant) and isinstance(v.value, str):
                parts.append(v.value)
            else:
                parts.append("<value>")
        return "".join(parts)
    return None


def from_python(source: str) -> list[tuple[int, str, bool]]:
    """(line, command, is code) for every command in a Python file's strings.

    Adjacent string literals are one string to Python, so they are joined
    before looking, and a command split across them is read whole.
    """
    try:
        module = ast.parse(source)
    except SyntaxError:
        return []
    out: list[tuple[int, str, bool]] = []
    seen: set[int] = set()
    # Docstrings are notes for whoever reads the code, not what an agent is told.
    for node in ast.walk(module):
        body = getattr(node, "body", None)
        if isinstance(body, list) and body and isinstance(body[0], ast.Expr):
            seen.add(id(body[0].value))
    for node in ast.walk(module):
        if isinstance(node, ast.JoinedStr):
            for v in node.values:
                seen.add(id(v))
        if id(node) in seen:
            continue
        text = _string_value(node)
        if not text or "mycelium " not in text:
            continue
        line = getattr(node, "lineno", 0)
        for span in _code_spans(text):
            out.extend((line, c, True) for c in _commands_in(span))
        rest = _IN_CODE.sub("", text)
        out.extend((line, c, False) for c in _commands_in(rest))
    return out


_TS_STRING = re.compile(r"[`\"']\s*(mycelium [^`\"'\n]+)")


def from_typescript(text: str) -> list[tuple[int, str, bool]]:
    """(line, command, is code) for strings in TypeScript that start with a command."""
    out: list[tuple[int, str, bool]] = []
    for n, line in enumerate(text.splitlines(), 1):
        for m in _TS_STRING.finditer(line):
            out.extend((n, c, True) for c in _commands_in(m.group(1)))
    return out


# ── the repository ───────────────────────────────────────────────────────────


def _files(root: Path) -> list[Path]:
    found: list[Path] = []
    for pattern in SOURCES:
        found.extend(p for p in root.glob(pattern) if p.is_file() and "node_modules" not in p.parts)
    return sorted(set(found))


def scan(root: Path, cli: Node | None = None) -> list[Finding]:
    """Every command in the repository's prose that the CLI would refuse."""
    cli = tree() if cli is None else cli
    findings: list[Finding] = []
    used: set[tuple[str, str]] = set()
    stale_hit: set[str] = set()
    this = Path(__file__).resolve()
    for path in _files(root):
        if path.resolve() == this:
            continue
        rel = path.relative_to(root).as_posix()
        if rel in STALE:
            stale_hit.add(rel)
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        if path.suffix == ".md":
            commands = from_markdown(text)
        elif path.suffix == ".py":
            commands = from_python(text)
        else:
            commands = from_typescript(text)
        for line, command, code in commands:
            problem = check(command, cli, code=code)
            if not problem:
                continue
            if (rel, command) in EXEMPT:
                used.add((rel, command))
                continue
            findings.append(Finding(rel, line, command, problem))
    for key, why in EXEMPT.items():
        if key not in used:
            findings.append(Finding(key[0], 0, key[1], f"exemption no longer needed ({why})"))
    for rel, where in STALE.items():
        if rel not in stale_hit:
            findings.append(Finding(rel, 0, "", f"listed as stale ({where}) but not found"))
            continue
        text = (root / rel).read_text(encoding="utf-8", errors="replace")
        if not any(check(c, cli, code=code) for _, c, code in from_markdown(text)):
            findings.append(Finding(rel, 0, "", f"listed as stale ({where}) but checks clean"))
    return findings


def repo_root() -> Path:
    """The checkout this package is installed from (editable), found by walking up."""
    here = Path(__file__).resolve()
    for parent in here.parents:
        if (parent / "mycelium-cli").is_dir() and (parent / "fastapi-backend").is_dir():
            return parent
    msg = "not inside a mycelium checkout"
    raise RuntimeError(msg)


def main() -> int:
    found = scan(repo_root())
    for f in found:
        print(f)  # noqa: T201
    print(f"{len(found)} finding{'s' if len(found) != 1 else ''}")  # noqa: T201
    return 1 if found else 0


if __name__ == "__main__":
    sys.exit(main())
