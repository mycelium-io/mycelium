# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""Who is calling: the hub, the handle, the room and the credential, in one place.

Every command needs four answers before it can talk to a room: which hub,
acting as whom, in which room, and with what credential. Each answer can come
from several places, and they are tried in the same order for all four:

1. **flag**: what the command was given (``--as``, ``--room``).
2. **environment**: what whoever started this process set, which is how an
   agent whose host passes it an environment is told who it is
   (``MYCELIUM_API_URL``, ``MYCELIUM_AGENT_HANDLE``, ``MYCELIUM_ROOM_ID``, the
   agent token variables).
3. **herdr pane**: the agent herdr's registry maps this process's pane to
   (``HERDR_PANE_ID``). herdr gives a pane the same id after its server
   restarts but brings the agent back without the environment it was started
   with, so this is how a restored agent is still told who it is.
4. **membership**: what ``mycelium join`` saved in this folder, found by walking
   up from the current folder the way git finds ``.git``. This is how an agent
   whose host passes it no environment knows who it is.
5. **machine**: this machine's own setup: ``config.toml``, ``mycelium login``,
   ``mycelium iam``, and the hub's ``whoami`` for that login.
6. **default**.

``identity.resolve_actor``, ``commands.room._resolve_room``,
``client.auth_headers`` and ``MyceliumConfig.load`` keep their signatures and
ask this module, so a way of running agents that needs a new source adds it
here, once. ``mycelium whoami --sources`` prints what each answer was and where
it came from (:func:`explain`).
"""

from __future__ import annotations

import contextlib
import json
import os
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from mycelium.config import MyceliumConfig

#: Where ``mycelium join`` saves a membership, under a folder's ``.mycelium/``.
MEMBERSHIP_FILE = "member.json"

HANDLE_ENV = "MYCELIUM_AGENT_HANDLE"
ROOM_ENVS = ("MYCELIUM_ROOM_ID", "MYCELIUM_CHANNEL_ID")
HUB_ENV = "MYCELIUM_API_URL"
#: What herdr sets in each of its panes, and keeps across its server's restarts.
PANE_ENV = "HERDR_PANE_ID"

FLAG, ENVIRONMENT, PANE, MEMBERSHIP, MACHINE, DEFAULT = (
    "flag",
    "environment",
    "pane",
    "membership",
    "machine",
    "default",
)


# ── membership: what `mycelium join` saved ───────────────────────────────────


@dataclass(frozen=True)
class Membership:
    """This folder's membership of a room, as ``mycelium join`` saved it."""

    hub: str
    room: str
    handle: str
    token: str | None
    token_expires_at: str | None
    joined_at: str
    #: The ``member.json`` it was read from.
    path: Path

    @property
    def folder(self) -> Path:
        """The folder that joined (the one holding ``.mycelium/``)."""
        return self.path.parent.parent

    def token_expired(self) -> bool:
        if not self.token_expires_at:
            return False
        try:
            return datetime.fromisoformat(self.token_expires_at) <= datetime.now(UTC)
        except ValueError:
            return False


def membership_path(folder: Path) -> Path:
    return folder / ".mycelium" / MEMBERSHIP_FILE


def find_membership(start: Path | None = None) -> Membership | None:
    """The membership of ``start`` (the current folder) or the nearest folder above it."""
    try:
        current = (start or Path.cwd()).resolve()
    except OSError:
        return None
    for folder in (current, *current.parents):
        path = membership_path(folder)
        if path.is_file():
            return _read(path)
    return None


def _read(path: Path) -> Membership | None:
    try:
        raw = json.loads(path.read_text())
    except (OSError, ValueError):
        return None
    if not isinstance(raw, dict) or not all(raw.get(k) for k in ("hub", "room", "handle")):
        return None
    return Membership(
        hub=str(raw["hub"]),
        room=str(raw["room"]),
        handle=str(raw["handle"]),
        token=raw.get("token") or None,
        token_expires_at=raw.get("token_expires_at") or None,
        joined_at=str(raw.get("joined_at") or ""),
        path=path,
    )


def save_membership(
    folder: Path,
    *,
    hub: str,
    room: str,
    handle: str,
    token: str | None,
    token_expires_at: str | None,
) -> Membership:
    """Save a membership in ``folder``: readable only by its owner, and ignored by git."""
    path = membership_path(folder)
    path.parent.mkdir(parents=True, exist_ok=True)
    ignore = path.parent / ".gitignore"
    if not ignore.exists():
        # A membership holds a token. Keep it out of the repository the agent
        # works in, whatever else that repository's .gitignore says, and keep
        # this file out too, so joining leaves nothing for `git status` to show.
        ignore.write_text(f"{MEMBERSHIP_FILE}\n.gitignore\n")
    body = {
        "hub": hub.rstrip("/"),
        "room": room,
        "handle": handle,
        "token": token,
        "token_expires_at": token_expires_at,
        "joined_at": datetime.now(UTC).isoformat(),
    }
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write(json.dumps(body, indent=2) + "\n")
    path.chmod(0o600)
    membership = _read(path)
    assert membership is not None  # noqa: S101 - we just wrote it
    return membership


def remove_membership(folder: Path) -> bool:
    path = membership_path(folder)
    if not path.exists():
        return False
    path.unlink()
    return True


# ── the herdr pane: who the registry says runs in this one ───────────────────


@dataclass(frozen=True)
class PaneAgent:
    """The agent herdr's registry maps this process's pane to.

    ``handle`` or ``room`` is ``None`` when the registry maps the pane to more
    than one, so neither is guessed.
    """

    pane: str
    handle: str | None
    room: str | None


def pane_agent() -> PaneAgent | None:
    """Who runs in this herdr pane, by the registry, or ``None`` outside one it maps."""
    pane = os.environ.get(PANE_ENV, "").strip()
    if not pane:
        return None
    from mycelium.integrations.herdr.bridge import HerdrRegistry

    try:
        mapped = [m for m in HerdrRegistry().all() if m.pane == pane]
    except OSError:
        return None
    if not mapped:
        return None
    handles = {m.handle.lstrip("@") for m in mapped}
    rooms = {m.room for m in mapped}
    return PaneAgent(
        pane=pane,
        handle=handles.pop() if len(handles) == 1 else None,
        room=rooms.pop() if len(rooms) == 1 else None,
    )


# ── the four answers ─────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Answer:
    value: str | None
    source: str


def config_overlay() -> dict[str, Any]:
    """What a membership says about the hub and the room, as config.

    ``MyceliumConfig.load`` merges this between the config files and the
    environment, so every reader of ``config.server.api_url`` and
    ``config.rooms.active`` sees the membership's answer, and an environment
    variable still wins over it.
    """
    member = find_membership()
    if member is None:
        return {}
    return {"server": {"api_url": member.hub}, "rooms": {"active": member.room}}


def hub(config: MyceliumConfig) -> Answer:
    """Which hub. ``config.server.api_url`` already holds the answer; this says why."""
    if os.environ.get(HUB_ENV):
        return Answer(os.environ[HUB_ENV], ENVIRONMENT)
    member = find_membership()
    if member is not None:
        return Answer(member.hub, MEMBERSHIP)
    return Answer(config.server.api_url, MACHINE)


def room(config: MyceliumConfig, flag: str | None = None) -> Answer:
    """Which room, or ``Answer(None, ...)`` when nothing says."""
    if flag:
        return Answer(flag, FLAG)
    for name in ROOM_ENVS:
        if os.environ.get(name):
            return Answer(os.environ[name], ENVIRONMENT)
    agent = pane_agent()
    if agent is not None and agent.room:
        return Answer(agent.room, PANE)
    member = find_membership()
    if member is not None:
        return Answer(member.room, MEMBERSHIP)
    if config.rooms.active:
        return Answer(config.rooms.active, MACHINE)
    return Answer(None, DEFAULT)


def handle(
    config: MyceliumConfig,
    flag: str | None = None,
    *,
    ask_hub: bool = True,
    fallback: str | None = None,
) -> Answer:
    """Acting as whom.

    The machine source asks the hub who this machine's login is (``ask_hub``)
    before the handle set with ``mycelium iam``, because a gated hub attributes a
    write to the token, not to what the CLI claims.

    A process in a herdr pane the registry maps to an agent is that agent, so
    when the pane can't say which one, it is told it is about to act as this
    machine instead.
    """
    from mycelium.identity import LEGACY_ACTOR_SENTINEL, _hub_whoami, get_current_handle

    if flag and flag != LEGACY_ACTOR_SENTINEL:
        return Answer(flag, FLAG)
    env_handle = os.environ.get(HANDLE_ENV, "").strip()
    if env_handle:
        return Answer(env_handle, ENVIRONMENT)
    agent = pane_agent()
    if agent is not None and agent.handle:
        return Answer(agent.handle, PANE)
    member = find_membership()
    if member is not None:
        return Answer(member.handle, MEMBERSHIP)
    answer = Answer(fallback, DEFAULT)
    if ask_hub:
        who = _hub_whoami(config)
        if who and who.get("handle"):
            answer = Answer(str(who["handle"]), MACHINE)
    if answer.source == DEFAULT:
        local = get_current_handle(config) or config.identity.name
        if local:
            answer = Answer(local, MACHINE)
    if agent is not None and answer.source == MACHINE:
        _warn_once(
            f"warning: herdr pane {agent.pane} belongs to more than one agent "
            f"({_pane_handles(agent.pane)}), so this acts as @{answer.value}, this "
            f"machine's identity. Pass --as <handle> to act as the agent.",
        )
    return answer


def _pane_handles(pane: str) -> str:
    from mycelium.integrations.herdr.bridge import HerdrRegistry

    return ", ".join(sorted({f"@{m.handle}" for m in HerdrRegistry().all() if m.pane == pane}))


_WARNED: set[str] = set()


def _warn_once(text: str) -> None:
    if text not in _WARNED:
        _WARNED.add(text)
        print(text, file=sys.stderr)


def credential(config: MyceliumConfig, acting_as: str | None = None) -> Answer:
    """The bearer token a call carries, or ``Answer(None, ...)`` for none.

    An agent's own credential comes first (``agent_credentials``: a token or a
    client from the environment, or one stored for that handle), then the
    membership's token when the call is made as that member, then this
    machine's ``mycelium login`` session.
    """
    from mycelium import agent_credentials
    from mycelium.client import current_token

    agent_token = agent_credentials.access_token(config, acting_as)
    if agent_token:
        return Answer(agent_token, ENVIRONMENT if _env_credential() else MACHINE)
    member = find_membership()
    if (
        member is not None
        and member.token
        and not member.token_expired()
        and (acting_as is None or _same_handle(acting_as, member.handle))
    ):
        return Answer(member.token, MEMBERSHIP)
    session = current_token(config)
    if session is not None:
        return Answer(session.access_token, MACHINE)
    return Answer(None, DEFAULT)


def _env_credential() -> bool:
    from mycelium import agent_credentials

    return any(
        os.environ.get(name)
        for name in (
            agent_credentials.STATIC_TOKEN_ENV,
            agent_credentials.CLIENT_ID_ENV,
        )
    )


def _same_handle(a: str, b: str) -> bool:
    def norm(h: str) -> str:
        return h.partition("#")[0].strip().lstrip("@").lower()

    return norm(a) == norm(b)


def explain(config: MyceliumConfig) -> list[tuple[str, str | None, str]]:
    """Each answer with where it came from: ``[(question, value, source), ...]``.

    The credential is reported by where it came from and whether there is one,
    never by its value.
    """
    cred = Answer(None, DEFAULT)
    with contextlib.suppress(Exception):
        cred = credential(config)
    return [
        ("hub", hub(config).value, hub(config).source),
        ("handle", *_pair(handle(config))),
        ("room", *_pair(room(config))),
        ("credential", "a token" if cred.value else None, cred.source),
    ]


def _pair(answer: Answer) -> tuple[str | None, str]:
    return answer.value, answer.source
