# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""Each agent's session on this machine, written where the desktop app reads it.

The rendered view beside an agent's terminal draws what the agent is doing from
its CLI's own session file. The runner follows those files for every agent in
this machine's herdr registry and writes each one's view to
``~/.mycelium/runner/sessions/<room>/<handle>.json``, which the app's
``agent_session`` command reads (``mycelium-desktop/src-tauri/src/session.rs``).
A file on this machine is the whole handoff: the app has no channel into the
runner, and nothing here reaches the hub (the screen rule).

Each file holds the ``AgentSession`` of ``mycelium-frontend/src/lib/agent-session.ts``,
or ``{"unavailable": "no_converter"}`` for a CLI Mycelium can't read, or
``{"unavailable": "no_session"}`` when its session file can't be found. A file
is written through a temporary one and renamed over, so the app never reads
half of one, and only when the session's files or the pane's state changed.
"""

from __future__ import annotations

import contextlib
import json
import logging
import os
import re
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING, Any

from mycelium.integrations.agents import of_kind
from mycelium.integrations.herdr.bridge import HerdrError, session_of

if TYPE_CHECKING:
    from mycelium.integrations.herdr.bridge import HerdrBridge

log = logging.getLogger(__name__)

#: How often the sessions are looked at.
SESSIONS_S = 1.0

#: herdr's state for an agent, as the view says it. A pane herdr can't read is
#: ``unknown``, and the view then claims nothing.
_STATE = {"working": "working", "blocked": "waiting", "idle": "idle", "done": "idle"}

#: A room or a handle that can be a file name here.
_SAFE = re.compile(r"[A-Za-z0-9_][A-Za-z0-9_.@-]{0,127}")


def sessions_dir() -> Path:
    from mycelium.runner.daemon import runner_dir

    return runner_dir() / "sessions"


#: Beside :func:`sessions_dir`: which member each session here has been.
MEMBERS_FILE = "session-members.json"


def remember_members(seen: dict[str, dict[str, str]], path: Path) -> None:
    """Keep which member each session here was (``seen``: session to ``{room,
    handle}``, from the herdr registry while that member is in it), so an
    earlier session can say whose it was after the member is gone. Written
    only when something is new. It is the runner's record, not the session's
    words, so the scan may carry it."""
    known = read_members(path)
    if all(known.get(s) == who for s, who in seen.items()):
        return
    known.update(seen)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(known, f)
        os.chmod(tmp, 0o600)
        os.replace(tmp, path)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(tmp)
        raise


def read_members(path: Path | None = None) -> dict[str, dict[str, str]]:
    """``{session: {room, handle}}`` for every session a member here has been in."""
    try:
        found = json.loads((path or sessions_dir().parent / MEMBERS_FILE).read_text("utf-8"))
    except (OSError, ValueError):
        return {}
    if not isinstance(found, dict):
        return {}
    return {
        str(s): {"room": str(who["room"]), "handle": str(who["handle"])}
        for s, who in found.items()
        if isinstance(who, dict) and who.get("room") and who.get("handle")
    }


class Follower:
    """Keeps each agent's session file current, one look at a time (:meth:`tick`)."""

    def __init__(self, bridge: HerdrBridge, base: Path | None = None) -> None:
        self.bridge = bridge
        self.base = base or sessions_dir()
        #: What each file was last written from, so an unchanged one isn't again.
        self._written: dict[tuple[str, str], tuple[Any, ...]] = {}

    def tick(self) -> None:
        try:
            live = {str(a["pane_id"]): a for a in self.bridge.list_agents() if a.get("pane_id")}
            up = True
        except HerdrError:
            live, up = {}, False
        kept: set[tuple[str, str]] = set()
        seen: dict[str, dict[str, str]] = {}
        for mapping in self.bridge.registry.all():
            if not (_SAFE.fullmatch(mapping.room) and _SAFE.fullmatch(mapping.handle)):
                continue
            key = (mapping.room, mapping.handle)
            kept.add(key)
            running = live.get(mapping.pane)
            state = _STATE.get(str((running or {}).get("agent_status") or ""), "unknown")
            if not up:
                state = "unknown"
            kind = of_kind(mapping.kind or (running or {}).get("agent"))
            session = session_of(running) or mapping.session
            folder = (
                mapping.cwd or (running or {}).get("foreground_cwd") or (running or {}).get("cwd")
            )
            if session:
                seen[session] = {"room": mapping.room, "handle": mapping.handle}
            try:
                self._follow(key, kind, session, folder, state)
            except Exception:  # noqa: BLE001 - one agent's file must not stop the others'
                log.exception(
                    "couldn't write the session of @%s in %s", mapping.handle, mapping.room
                )
        for gone in set(self._written) - kept:
            self._remove(gone)
        try:
            remember_members(seen, self.base.parent / MEMBERS_FILE)
        except OSError:
            log.exception("couldn't keep which member each session was")

    def _follow(
        self, key: tuple[str, str], kind: Any, session: str | None, folder: str | None, state: str
    ) -> None:
        if not kind.renders:
            self._write(key, ("no_converter",), {"unavailable": "no_converter"})
            return
        path = kind.session_path(folder, session) if session else None
        if path is None:
            self._write(key, ("no_session",), {"unavailable": "no_session"})
            return
        stamp = (str(path), state, *(_stamp(p) for p in kind.session_files(path)))
        if self._written.get(key) == stamp:
            return
        body = kind.read_session(path)
        self._write(key, stamp, {**body, "state": state, "waitingOn": None}, force=True)

    def _write(
        self,
        key: tuple[str, str],
        stamp: tuple[Any, ...],
        body: dict[str, Any],
        *,
        force: bool = False,
    ) -> None:
        if not force and self._written.get(key) == stamp:
            return
        folder = self.base / key[0]
        folder.mkdir(parents=True, exist_ok=True, mode=0o700)
        fd, tmp = tempfile.mkstemp(dir=folder, prefix=".", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(body, f)
            os.chmod(tmp, 0o600)
            os.replace(tmp, folder / f"{key[1]}.json")
        except BaseException:
            with contextlib.suppress(OSError):
                os.unlink(tmp)
            raise
        self._written[key] = stamp

    def _remove(self, key: tuple[str, str]) -> None:
        self._written.pop(key, None)
        with contextlib.suppress(OSError):
            (self.base / key[0] / f"{key[1]}.json").unlink()


def page(
    kind_name: str | None, folder: str | None, session: str | None, before: str, limit: int
) -> dict[str, Any]:
    """``{entries, earlier}``: the ``limit`` entries just before ``before`` in an
    agent's session, for the rendered view's earlier pages; or ``{"unavailable":
    "no_converter" | "no_session" | "no_entry"}``. Read here, never sent to the hub."""
    kind = of_kind(kind_name)
    if not kind.renders:
        return {"unavailable": "no_converter"}
    path = kind.session_path(folder, session) if session else None
    if path is None:
        return {"unavailable": "no_session"}
    found = kind.read_session_page(path, before, limit)
    return found if found is not None else {"unavailable": "no_entry"}


def _stamp(path: Path) -> tuple[int, int]:
    try:
        st = path.stat()
    except OSError:
        return (0, 0)
    return (st.st_mtime_ns, st.st_size)
