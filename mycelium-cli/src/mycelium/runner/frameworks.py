# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""The scan: which agent CLIs this machine can start.

What can be started is herdr's call, read from ``herdr agent start --help``
rather than listed here, so a herdr that learns a new kind makes it startable
with no change to this file. herdr never looks for a CLI's program: it types
the command at an interactive prompt in a pane, where the person's own shell
finds it on their real PATH. So every kind herdr has is offered, and the start
is the test of whether it's installed: one whose shell can't find it says so,
with where to install it (``Runner._start_failed``). The scan doesn't look for
programs itself. What to call each CLI is the table in
:mod:`mycelium.integrations.agents`.

:func:`locate` still finds a CLI's program for the few times the runner runs
it before a start (Codex's ``--help`` and ``login status``): on this process's
``PATH``, then in the folders version managers put programs in
(:func:`install_dirs`). Nothing of the person's runs to answer it: not their
shell, not its rc files.
"""

from __future__ import annotations

import os
import re
import shutil
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from mycelium.integrations.agents import KNOWN, by_id

if TYPE_CHECKING:
    from collections.abc import Iterable


@dataclass
class Found:
    """One framework as the scan saw it; the wire shape of ``FrameworkRead``."""

    id: str
    name: str
    command: str
    path: str | None
    version: str | None
    installed: bool
    launchable: bool
    note: str | None
    #: Its earlier sessions here that can be brought into a room (see
    #: :func:`with_sessions`); ``None`` when its integration can't list them.
    sessions: list[dict[str, Any]] | None = None

    def wire(self) -> dict:
        return asdict(self)


#: What the scan says about a session. It reaches the hub, so it says where and
#: when, never what was said in it: no title, nothing from inside the file.
SESSION_FIELDS = ("id", "folder", "last_used", "branch")


def with_sessions(
    found: list[Found],
    *,
    roots: list[Path],
    busy: set[str],
    members: dict[str, dict[str, str]] | None = None,
) -> list[Found]:
    """``found`` with the earlier sessions of each CLI here that could be
    brought into a room: in a folder that is still there, inside ``roots``
    (where a launch may start), and not one an agent here is already in
    (``busy``). Each says which ``member`` it was, from the runner's own record
    (``members``), or ``None``. A CLI whose integration can't list them keeps
    ``None``."""
    members = members or {}
    for f in found:
        kind = by_id(f.id)
        if kind is None or not (f.installed or f.launchable):
            continue
        try:
            listed = kind.list_sessions()
        except OSError:
            listed = None
        if listed is None:
            continue
        f.sessions = [
            {**{k: s.get(k) for k in SESSION_FIELDS}, "member": members.get(str(s.get("id")))}
            for s in listed
            if s.get("id") not in busy and _can_start_in(s.get("folder"), roots)
        ]
    return found


def _can_start_in(folder: Any, roots: list[Path]) -> bool:
    if not isinstance(folder, str) or not folder:
        return False
    path = Path(folder)
    if not path.is_dir():
        return False
    path = path.resolve()
    return any(path == root or root in path.parents for root in roots)


def _newest_first(dirs: Iterable[Path]) -> list[Path]:
    """Version managers' folders, the newest version first, read from the
    ``v24.1.0``-style part of each path."""

    def version(p: Path) -> tuple[int, ...]:
        for part in reversed(p.parts):
            if m := re.fullmatch(r"v?(\d+(?:\.\d+)*)", part):
                return tuple(int(n) for n in m.group(1).split("."))
        return ()

    return sorted(dirs, key=version, reverse=True)


def install_dirs() -> list[Path]:
    """Where agent CLIs are commonly installed when they're not on this
    process's PATH: nvm's Node versions (newest first), Volta, fnm, asdf's
    shims, Bun, ``~/.local/bin`` and Homebrew's folders. The desktop app starts
    the runner without the PATH a terminal has, and these are what a terminal
    usually adds."""
    home = Path.home()
    nvm = Path(os.environ.get("NVM_DIR") or home / ".nvm") / "versions" / "node"
    fnm = [Path(d) for d in (os.environ.get("FNM_DIR"),) if d] + [
        home / ".local" / "share" / "fnm",
        home / "Library" / "Application Support" / "fnm",
    ]
    asdf = Path(os.environ.get("ASDF_DATA_DIR") or home / ".asdf")
    return [
        *_newest_first(nvm.glob("*/bin")),
        home / ".volta" / "bin",
        *(d / "aliases" / "default" / "bin" for d in fnm),
        *_newest_first(p for d in fnm for p in d.glob("node-versions/*/installation/bin")),
        asdf / "shims",
        home / ".bun" / "bin",
        home / ".local" / "bin",
        Path("/opt/homebrew/bin"),
        Path("/usr/local/bin"),
    ]


def locate(binaries: tuple[str, ...]) -> tuple[str | None, str | None]:
    """The first of ``binaries`` on this process's PATH, else in
    :func:`install_dirs`, and the PATH to run it with: ``None`` for this
    process's own, or that folder ahead of it, so a CLI that's a Node script
    (``#!/usr/bin/env node``) finds the ``node`` installed beside it.
    ``(None, None)`` when it isn't found."""
    if found := next((p for b in binaries if (p := shutil.which(b))), None):
        return found, None
    for folder in install_dirs():
        if found := next((p for b in binaries if (p := shutil.which(b, path=str(folder)))), None):
            return found, f"{folder}{os.pathsep}{os.environ.get('PATH', os.defpath)}"
    return None, None


def scan(kinds: set[str] | None, *, host: str = "herdr") -> list[Found]:
    """Every known framework, what the host can start first.

    ``kinds`` is what the runner's host (named ``host``) says it can start, or
    ``None`` when the host is not here. A framework is launchable when the host
    has its kind; whether it's installed is found out by starting it.

    ``path`` and ``version`` are always ``None`` and ``installed`` is the same
    as ``launchable``: the wire still carries them for apps from before the
    scan stopped looking for programs, which would otherwise list every CLI as
    not found.
    """
    out: list[Found] = []
    for k in KNOWN:
        host_can = bool(k.herdr_kind and kinds is not None and k.herdr_kind in kinds)
        note = None
        if kinds is None:
            note = f"{host} isn't running here"
        elif k.herdr_kind is None:
            note = f"{host} has no {k.id} kind yet"
        elif not host_can:
            note = f"this {host} can't start {k.herdr_kind}; it may need updating"
        out.append(
            Found(
                id=k.id,
                name=k.name,
                command=k.binaries[0],
                path=None,
                version=None,
                installed=host_can,
                launchable=host_can,
                note=note,
            )
        )
    out.sort(key=lambda f: not f.launchable)
    return out
