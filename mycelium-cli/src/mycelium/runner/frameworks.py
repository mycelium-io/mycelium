# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""The scan: which agent CLIs are on this machine, and which herdr can start.

A framework is found by its executable on ``PATH``. Whether it can be started
is herdr's call, read from ``herdr agent start --help`` rather than listed
here, so a herdr that learns a new kind makes it startable with no change to
this file. The table below only names what to look for and what to call it.
"""

from __future__ import annotations

import shutil
import subprocess
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass

#: How long one ``--version`` may take before the scan gives up on it.
VERSION_TIMEOUT_S = 4.0


@dataclass(frozen=True)
class Known:
    """An agent CLI the scan looks for."""

    id: str
    name: str
    #: Executables that mean it is installed, first match wins.
    binaries: tuple[str, ...]
    #: The kind herdr starts it as, when herdr has one.
    herdr_kind: str | None


KNOWN: tuple[Known, ...] = (
    Known("claude", "Claude Code", ("claude",), "claude"),
    Known("codex", "Codex", ("codex",), "codex"),
    Known("gemini", "Gemini CLI", ("gemini",), "gemini"),
    Known("cursor", "Cursor Agent", ("cursor-agent",), "cursor"),
    Known("opencode", "OpenCode", ("opencode",), "opencode"),
    Known("pi", "Pi", ("pi",), "pi"),
    Known("copilot", "GitHub Copilot CLI", ("copilot",), "copilot"),
    Known("amp", "Amp", ("amp",), "amp"),
    Known("droid", "Droid", ("droid",), "droid"),
    Known("cline", "Cline", ("cline",), "cline"),
    Known("kiro", "Kiro", ("kiro-cli", "kiro"), "kiro"),
    Known("kimi", "Kimi", ("kimi",), "kimi"),
    Known("grok", "Grok", ("grok",), "grok"),
    Known("goose", "Goose", ("goose",), None),
    Known("aider", "Aider", ("aider",), None),
)


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


def _version(path: str) -> str | None:
    try:
        proc = subprocess.run(  # noqa: S603 - a path found on PATH, fixed argument
            [path, "--version"],
            capture_output=True,
            text=True,
            timeout=VERSION_TIMEOUT_S,
            check=False,
            stdin=subprocess.DEVNULL,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    line = next(
        (ln.strip() for ln in (proc.stdout or proc.stderr or "").splitlines() if ln.strip()), ""
    )
    return line[:60] or None


def by_id(framework_id: str) -> Known | None:
    return next((k for k in KNOWN if k.id == framework_id), None)


def scan(herdr_kinds: set[str] | None) -> list[Found]:
    """Every known framework, installed ones first.

    ``herdr_kinds`` is what herdr says it can start (``None`` when herdr is not
    here); a framework is launchable when it is installed and herdr has its kind.
    """
    located = {k.id: next((p for b in k.binaries if (p := shutil.which(b))), None) for k in KNOWN}
    with ThreadPoolExecutor(max_workers=8) as pool:
        versions = dict(
            zip(
                [k.id for k in KNOWN if located[k.id]],
                pool.map(_version, [located[k.id] for k in KNOWN if located[k.id]]),
                strict=True,
            )
        )

    out: list[Found] = []
    for k in KNOWN:
        path = located[k.id]
        herdr_can = bool(k.herdr_kind and herdr_kinds is not None and k.herdr_kind in herdr_kinds)
        note = None
        if path and not herdr_can:
            if herdr_kinds is None:
                note = "herdr isn't running here"
            elif k.herdr_kind is None:
                note = f"herdr has no {k.id} kind yet"
            else:
                note = f"this herdr can't start {k.herdr_kind}; update herdr"
        out.append(
            Found(
                id=k.id,
                name=k.name,
                command=k.binaries[0],
                path=path,
                version=versions.get(k.id),
                installed=path is not None,
                launchable=path is not None and herdr_can,
                note=note,
            )
        )
    out.sort(key=lambda f: (not f.installed, not f.launchable))
    return out
