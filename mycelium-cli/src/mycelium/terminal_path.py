# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""The folders a terminal's PATH usually adds, for a process started without one.

The desktop app starts without the PATH a terminal has. Two things run a
program before any terminal is involved and need to find it the way a terminal
would: the runner's checks of Codex before starting it (its ``--help`` and
``login status``), and the commands widgets run. They look here.

These are the common places programs are installed (Homebrew, nvm and other
version managers), never a folder for any one program. Whether an agent CLI is
installed is never decided here: herdr starts it in a terminal, and that
start says. Nothing of the person's runs to answer it: not their shell, not
its rc files.
"""

from __future__ import annotations

import os
import re
import shutil
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterable


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
    """Where programs are commonly installed when they're not on this
    process's PATH: nvm's Node versions (newest first), Volta, fnm, asdf's
    shims, Bun, ``~/.local/bin`` and Homebrew's folders."""
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
    process's own, or that folder ahead of it, so a program that's a Node
    script (``#!/usr/bin/env node``) finds the ``node`` installed beside it.
    ``(None, None)`` when it isn't found."""
    if found := next((p for b in binaries if (p := shutil.which(b))), None):
        return found, None
    for folder in install_dirs():
        if found := next((p for b in binaries if (p := shutil.which(b, path=str(folder)))), None):
            return found, f"{folder}{os.pathsep}{os.environ.get('PATH', os.defpath)}"
    return None, None
