# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""The scan: which agent CLIs are on this machine, and which herdr can start.

A framework is found by its executable on ``PATH``, or failing that on the
PATH a new terminal tab has (:func:`terminal_path`). A CLI installed under a
version manager such as nvm is only on the PATH that ``~/.zshrc`` sets up, and
the desktop app starts the runner from a login shell, which doesn't read it.
herdr starts agents in a pane at an interactive prompt, which does, so what
that PATH finds, herdr can start. Whether it can be started is herdr's call,
read from ``herdr agent start --help`` rather than listed here, so a herdr that
learns a new kind makes it startable with no change to this file. What to look
for and what to call it is the table in :mod:`mycelium.integrations.agents`.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass

from mycelium.integrations.agents import KNOWN

#: How long one ``--version`` may take before the scan gives up on it.
VERSION_TIMEOUT_S = 4.0
#: How long the person's interactive shell may take to say its PATH. A slow or
#: stuck ``~/.zshrc`` costs a scan this much, then the scan goes on with the
#: PATH it has.
SHELL_TIMEOUT_S = 5.0
#: How long the terminal's PATH is kept before it's asked for again.
SHELL_PATH_TTL_S = 300.0
#: Around the PATH in the shell's output, so whatever an rc file prints (a
#: greeting, a warning) can't be read as part of it.
_MARK = "__mycelium_path__"
_asked: tuple[float, str | None] | None = None


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


def terminal_path() -> str | None:
    """The PATH a new terminal tab has: what the person's shell sets up when
    it starts interactively (``$SHELL -ilc``), so ``~/.zshrc`` and the version
    managers it loads count. ``None`` on Windows, with no ``$SHELL``, or when
    the shell doesn't answer in time. Kept for :data:`SHELL_PATH_TTL_S`."""
    global _asked  # noqa: PLW0603 - one answer per process, asked again by age
    now = time.monotonic()
    if _asked is not None and now - _asked[0] < SHELL_PATH_TTL_S:
        return _asked[1]
    shell = os.environ.get("SHELL")
    found: str | None = None
    if shell and sys.platform != "win32":
        try:
            proc = subprocess.run(  # noqa: S603 - the person's own shell, fixed script
                [shell, "-ilc", f'printf "{_MARK}%s{_MARK}" "$PATH"'],
                capture_output=True,
                text=True,
                timeout=SHELL_TIMEOUT_S,
                check=False,
                stdin=subprocess.DEVNULL,
            )
            match = re.search(f"{_MARK}(.*?){_MARK}", proc.stdout or "", re.DOTALL)
            found = (match.group(1).strip() or None) if match else None
        except (OSError, subprocess.TimeoutExpired):
            found = None
    _asked = (now, found)
    return found


def _locate(binaries: tuple[str, ...], search_path: str | None) -> str | None:
    """The first of ``binaries`` on ``search_path`` (this process's PATH when
    ``None``), or ``None``."""
    return next((p for b in binaries if (p := shutil.which(b, path=search_path))), None)


def _version(path: str, search_path: str | None = None) -> str | None:
    """``<path> --version``'s first line. ``search_path`` is the PATH it runs
    with when it was found on another: a CLI that's a Node script
    (``#!/usr/bin/env node``) needs that PATH's ``node``."""
    env = {**os.environ, "PATH": search_path} if search_path else None
    try:
        proc = subprocess.run(  # noqa: S603 - a path found on PATH, fixed argument
            [path, "--version"],
            capture_output=True,
            text=True,
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
    """Every known framework, installed ones first.

    ``kinds`` is what the runner's host (named ``host``) says it can start, or
    ``None`` when the host is not here; a framework is launchable when it is
    installed and the host has its kind.
    """
    located: dict[str, tuple[str | None, str | None]] = {
        k.id: (_locate(k.binaries, None), None) for k in KNOWN
    }
    # The terminal's PATH is asked for only when something isn't found here.
    if any(path is None for path, _ in located.values()) and (terminal := terminal_path()):
        for k in KNOWN:
            if located[k.id][0] is None and (path := _locate(k.binaries, terminal)):
                located[k.id] = (path, terminal)
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
        if path and not host_can:
            if kinds is None:
                note = f"{host} isn't running here"
            elif k.herdr_kind is None:
                note = f"{host} has no {k.id} kind yet"
            else:
                note = f"this {host} can't start {k.herdr_kind}; it may need updating"
        out.append(
            Found(
                id=k.id,
                name=k.name,
                command=k.binaries[0],
                path=path,
                version=versions.get(k.id),
                installed=path is not None,
                launchable=path is not None and host_can,
                note=note,
            )
        )
    out.sort(key=lambda f: (not f.installed, not f.launchable))
    return out
