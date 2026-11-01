# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""Check every command's flags against the shapes in ``cli_options``.

Read from the CLI itself, not from a list: every command Typer would build is
walked, and each shared flag is checked wherever it appears. A command that
reads something must also say it in JSON, with ``--json`` after the command,
and one that writes as someone (its code asks who is acting) must take ``--as``.
Where a command legitimately differs, it is named in ``EXEMPT`` with why, and
an exemption that no longer applies is a finding too.

    uv run python -m mycelium.cli_audit            # the findings
    uv run python -m mycelium.cli_audit --table    # every command's flags

``tests/test_cli_audit.py`` runs it, so a new command that drifts fails CI.
"""

from __future__ import annotations

import inspect
import sys
import types
from dataclasses import dataclass, field
from typing import Any

from mycelium.cli_options import ACT_FLAGS, JSON_FLAGS, LIMIT_FLAGS, ROOM_FLAGS, YES_FLAGS

#: The last word of a command that reads rather than changes something. Each
#: one answers in JSON with `--json`.
READ_VERBS = frozenset(
    {
        "ls", "list", "show", "get", "search", "messages", "log", "status", "settings",
        "whoami", "links", "context", "decisions", "procedures", "work", "scan",
        "version", "summary", "errors", "events", "slow", "rooms", "agents", "schema",
        "show-attrs", "by-agent", "by-channel", "by-host", "by-model", "by-name",
        "by-room", "by-tool", "integrations",
    }
)  # fmt: skip

#: Commands that take text an agent writes (see ``text_input.takes_text``).
TEXT_COMMANDS = frozenset(
    {
        "respond", "room send", "room amend", "board send", "agent invoke",
        "memory set", "skill set",
    }
)  # fmt: skip

#: Calls that answer "who is acting". A command whose code makes one, itself or
#: through a helper in its own module, acts as someone, so it takes ``--as``.
ACTOR_LOOKUPS = frozenset({"get_current_identity", "resolve_actor", "resolve_handle"})

#: Commands that differ on purpose, with why.
EXEMPT: dict[tuple[str, str], str] = {
    ("docs ls", "json"): "lists the docs bundled with the CLI for a person to open",
    ("iam", "as"): "sets who this machine acts as; the handle it takes is that answer",
    ("herdr enroll", "as"): "registers the agent as this machine's owner, named by --owner",
    ("herdr sync", "as"): "registers members as this machine's owner, not as who runs it",
}


@dataclass
class Command:
    path: str
    flags: dict[str, set[str]] = field(default_factory=dict)  # param name -> its flags
    required: set[str] = field(default_factory=set)
    acts: bool = False  # its code asks who is acting

    def has(self, flag: str) -> bool:
        return any(flag in f for f in self.flags.values())

    def holding(self, flag: str) -> list[set[str]]:
        return [f for f in self.flags.values() if flag in f]


def commands() -> list[Command]:
    """Every leaf command the CLI builds, with each option's flags."""
    import typer.main

    from mycelium.cli import app

    out: list[Command] = []

    def walk(group: Any, path: list[str]) -> None:
        for name, sub in sorted(getattr(group, "commands", {}).items()):
            here = [*path, name]
            if getattr(sub, "hidden", False):
                continue
            if hasattr(sub, "commands"):
                walk(sub, here)
                continue
            cmd = Command(" ".join(here), acts=_asks_who_acts(sub.callback))
            for p in sub.params:
                flags = {*getattr(p, "opts", []), *getattr(p, "secondary_opts", [])}
                flags = {f for f in flags if f.startswith("-")}
                if flags:
                    cmd.flags[p.name] = flags
                    if p.required:
                        cmd.required.add(p.name)
            out.append(cmd)

    walk(typer.main.get_command(app), [])
    return out


def _asks_who_acts(callback: Any) -> bool:
    """Whether a command's code looks up who is acting.

    Read from its compiled code: the names it calls, its nested functions, and
    any function of its own module it calls, followed the same way.
    """
    if callback is None:
        return False
    fn = inspect.unwrap(callback)
    module = getattr(fn, "__module__", None)
    scope = getattr(fn, "__globals__", {})
    seen: set[types.CodeType] = set()

    def looks(code: types.CodeType) -> bool:
        if code in seen:
            return False
        seen.add(code)
        if ACTOR_LOOKUPS & set(code.co_names):
            return True
        nested = (c for c in code.co_consts if isinstance(c, types.CodeType))
        helpers = (
            f.__code__
            for n in code.co_names
            if isinstance(f := scope.get(n), types.FunctionType) and f.__module__ == module
        )
        return any(looks(c) for c in (*nested, *helpers))

    code = getattr(fn, "__code__", None)
    return looks(code) if code is not None else False


def _is_read(cmd: Command) -> bool:
    return cmd.path.split()[-1] in READ_VERBS


def findings(cmds: list[Command] | None = None) -> list[str]:
    """What breaks a rule, one line each."""
    cmds = commands() if cmds is None else cmds
    found: list[str] = []
    used: set[tuple[str, str]] = set()

    def exempt(cmd: Command, rule: str) -> bool:
        key = (cmd.path, rule)
        if key in EXEMPT:
            used.add(key)
            return True
        return False

    for cmd in cmds:
        for flags in cmd.holding("--room"):
            if not set(ROOM_FLAGS) <= flags and not exempt(cmd, "room"):
                found.append(f"{cmd.path}: --room should be spelled {'/'.join(ROOM_FLAGS)}")
        for name, flags in cmd.flags.items():
            if flags & {"--as", "--handle"}:
                if not set(ACT_FLAGS) <= flags and not exempt(cmd, "as"):
                    found.append(f"{cmd.path}: --as should be spelled {'/'.join(ACT_FLAGS)}")
                if name in cmd.required and not exempt(cmd, "as"):
                    found.append(f"{cmd.path}: --as should not be required (it resolves)")
        if cmd.acts and not _is_read(cmd) and not cmd.has("--as") and not exempt(cmd, "as"):
            found.append(f"{cmd.path}: writes as someone, so it should take --as")
        for flags in cmd.holding("--limit"):
            if not set(LIMIT_FLAGS) <= flags and not exempt(cmd, "limit"):
                found.append(f"{cmd.path}: --limit should be spelled {'/'.join(LIMIT_FLAGS)}")
        for flags in cmd.holding("--yes"):
            if not set(YES_FLAGS) <= flags and not exempt(cmd, "yes"):
                found.append(f"{cmd.path}: --yes should be spelled {'/'.join(YES_FLAGS)}")
        if _is_read(cmd) and not cmd.has(JSON_FLAGS[0]) and not exempt(cmd, "json"):
            found.append(f"{cmd.path}: reads something, so it should take --json")
        if cmd.path in TEXT_COMMANDS and not (cmd.has("--body") and cmd.has("--file")):
            found.append(f"{cmd.path}: takes text, so it should take --body and --file")

    paths = {c.path for c in cmds}
    for key, why in EXEMPT.items():
        if key[0] not in paths:
            found.append(f"exemption for {key[0]!r} ({why}) names no command")
        elif key not in used:
            found.append(f"exemption for {key[0]!r} {key[1]} is no longer needed")
    return found


def table(cmds: list[Command] | None = None) -> str:
    """Every command and which shared flags it takes."""
    cmds = commands() if cmds is None else cmds
    cols = [("room", "--room"), ("as", "--as"), ("json", "--json"), ("limit", "--limit"),
            ("yes", "--yes"), ("body", "--body")]  # fmt: skip
    width = max(len(c.path) for c in cmds)
    head = "command".ljust(width) + "  " + "  ".join(c for c, _ in cols)
    rows = [
        c.path.ljust(width)
        + "  "
        + "  ".join(("x" if c.has(f) else ".").ljust(len(n)) for n, f in cols)
        for c in cmds
    ]
    return "\n".join([head, *rows])


def main(argv: list[str]) -> int:
    if "--table" in argv:
        print(table())  # noqa: T201
        return 0
    found = findings()
    for line in found:
        print(line)  # noqa: T201
    print(f"{len(found)} finding{'s' if len(found) != 1 else ''}")  # noqa: T201
    return 1 if found else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
