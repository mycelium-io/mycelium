# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""The scan: which agent CLIs this machine can start, and which look installed.

What can be started is herdr's call, read from ``herdr agent start --help``
rather than listed here, so a herdr that learns a new kind makes it startable
with no change to this file. herdr never looks for a CLI's program: it types
the command at an interactive prompt in a pane, where the person's own shell
finds it on their real PATH. So every kind herdr has is offered, found or not,
and the start is the real test of whether it's installed.

Whether a CLI is found is a hint for the list, and for asking an installed CLI
about its flags: its program on this process's ``PATH``, then in the folders
version managers and installers put programs in (:func:`install_dirs`).
Nothing of the person's runs to answer it: not their shell, not its rc files.
What to look for and what to call it is the table in
:mod:`mycelium.integrations.agents`.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from mycelium.integrations.agents import KNOWN

if TYPE_CHECKING:
    from collections.abc import Iterable

#: How long one ``--version`` may take before the scan gives up on it.
VERSION_TIMEOUT_S = 4.0


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

    def wire(self) -> dict:
        return asdict(self)


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


def _version(path: str, search_path: str | None = None) -> str | None:
    """``<path> --version``'s first line, run with ``search_path`` as its PATH
    when it was found outside this process's."""
    env = {**os.environ, "PATH": search_path} if search_path else None
    try:
        proc = subprocess.run(  # noqa: S603 - a path the scan found, fixed argument
            [path, "--version"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=VERSION_TIMEOUT_S,
            check=False,
            stdin=subprocess.DEVNULL,
            env=env,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    line = next(
        (ln.strip() for ln in (proc.stdout or proc.stderr or "").splitlines() if ln.strip()), ""
    )
    return line[:60] or None


def scan(kinds: set[str] | None, *, host: str = "herdr") -> list[Found]:
    """Every known framework: what the host can start first, found ones first
    among those.

    ``kinds`` is what the runner's host (named ``host``) says it can start, or
    ``None`` when the host is not here. A framework is launchable when the host
    has its kind, whether or not the scan found its program: the host's shell
    may find what the scan didn't.
    """
    located = {k.id: locate(k.binaries) for k in KNOWN}
    found = [k.id for k in KNOWN if located[k.id][0]]
    with ThreadPoolExecutor(max_workers=8) as pool:
        versions = dict(
            zip(
                found,
                pool.map(lambda i: _version(str(located[i][0]), located[i][1]), found),
                strict=True,
            )
        )

    out: list[Found] = []
    for k in KNOWN:
        path = located[k.id][0]
        host_can = bool(k.herdr_kind and kinds is not None and k.herdr_kind in kinds)
        note = None
        if kinds is None:
            note = f"{host} isn't running here"
        elif k.herdr_kind is None:
            note = f"{host} has no {k.id} kind yet"
        elif not host_can:
            note = f"this {host} can't start {k.herdr_kind}; it may need updating"
        elif path is None:
            note = "not found on this machine"
        out.append(
            Found(
                id=k.id,
                name=k.name,
                command=k.binaries[0],
                path=path,
                version=versions.get(k.id),
                installed=path is not None,
                launchable=host_can,
                note=note,
            )
        )
    out.sort(key=lambda f: (not f.launchable, not f.installed))
    return out
