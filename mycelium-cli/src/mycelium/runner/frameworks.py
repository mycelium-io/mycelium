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
programs. What Mycelium knows about each CLI, beyond herdr's name for it, is
the table in :mod:`mycelium.integrations.agents`.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from mycelium.integrations.agents import KNOWN, by_id


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


def scan(kinds: set[str] | None, *, host: str = "herdr") -> list[Found]:
    """Every agent CLI the host can start, then the known ones it can't.

    ``kinds`` is what the runner's host (named ``host``) says it can start, or
    ``None`` when the host is not here. A framework is launchable when the host
    has its kind; whether it's installed is found out by starting it. A kind the
    host has that :mod:`mycelium.integrations.agents` doesn't know is offered
    too, by the host's name for it: what the table adds is only what Mycelium
    knows about a CLI (its name, arguments, install page).

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
    known = {k.id for k in KNOWN} | {k.herdr_kind for k in KNOWN if k.herdr_kind}
    # herdr names a kind by its canonical executable, which is all there is to call it.
    out.extend(
        Found(
            id=kind,
            name=kind,
            command=kind,
            path=None,
            version=None,
            installed=True,
            launchable=True,
            note=None,
        )
        for kind in sorted((kinds or set()) - known)
    )
    out.sort(key=lambda f: not f.launchable)
    return out
