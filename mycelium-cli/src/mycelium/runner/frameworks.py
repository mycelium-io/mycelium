# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""The scan: which agent CLIs are on this machine, and which herdr can start.

A framework is found by its executable on ``PATH``. Whether it can be started
is herdr's call, read from ``herdr agent start --help`` rather than listed
here, so a herdr that learns a new kind makes it startable with no change to
this file. What to look for and what to call it is the table in
:mod:`mycelium.integrations.agents`.
"""

from __future__ import annotations

import shutil
import subprocess
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass

from mycelium.integrations.agents import KNOWN

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


def scan(kinds: set[str] | None, *, host: str = "herdr") -> list[Found]:
    """Every known framework, installed ones first.

    ``kinds`` is what the runner's host (named ``host``) says it can start, or
    ``None`` when the host is not here; a framework is launchable when it is
    installed and the host has its kind.
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
