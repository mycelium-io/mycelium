# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""Shared in-process fakes for the backend test suite.

One import gets you a fake room: no Pi binary, no live LLM. This module is the
single, shared home for the backend test fakes.

What stands in for what:

* :class:`FakePersister`: the log side of ``RoomPersister``
  (``app.services.persister``): a ``DeliveryLog``, plus every message recorded
  through it, and optionally a simulated member who answers each prompt.
* :class:`FakeManaged` / :class:`FakeManager`: ``ManagedRoomChannel`` /
  ``RoomChannelManager`` (``app.services.room_channels``).
* :func:`patch_pi_run`: mock ``subprocess.run`` / ``shutil.which`` so ``PiSession``
  never spawns a real ``pi``.

See ``tests/README.md`` for the "test a feature without a live stack" recipe.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from app.services import message_format
from app.services.message_format import serialize_content
from app.services.message_models import Kind
from app.services.persister import DeliveryLog, TranscriptRecord, record_from

if TYPE_CHECKING:
    from collections.abc import Callable

    import pytest

# The default room the fakes and the simulated participant replies are stamped for.
DEFAULT_ROOM = "align-room"
EPISODE = message_format.episode_urn(DEFAULT_ROOM, "live")
TOPIC = message_format.topic_urn(DEFAULT_ROOM)


def position_record(
    sender: str,
    *,
    confidence: float | None = None,
    action: str = "accept",
    role: str = "agent",
    payload_type: str = "reply",
    message_id: str | None = None,
    episode: str = EPISODE,
    topic: str = TOPIC,
    prose: str | None = None,
) -> TranscriptRecord:
    """An agent-position transcript record carrying an epistemic payload.

    ``prose`` is the message body; it defaults to a stub.
    """
    data: dict[str, Any] = {"action": action}
    if confidence is not None:
        data["confidence"] = confidence
    env = message_format.build_envelope(
        kind=Kind.exchange,
        episode=episode,
        sender=sender,
        sender_role=role,
        recipients=[message_format.SYSTEM_ACTOR_ID],
        topic=topic,
        payload_type=payload_type,
        payload_data=data,
        message_id=message_id,
    )
    return record_from(
        env, serialize_content(env, extra={"content": prose or f"{sender} position"})
    )


# ── The room's log (what an engine posts through) ────────────────────────────


class FakePersister:
    """The log side of ``RoomPersister``: a ``DeliveryLog`` plus ``record``.

    Every message recorded through it lands in :attr:`recorded` as
    ``(envelope, content)``; ``content["content"]`` is the message's text.
    What is recorded is not appended to :attr:`log`, so an engine reading the
    log sees only what a test put there (or a simulated reply).

    With ``reply_conf`` set, every ``exchange`` prompt draws a simulated reply
    from each addressed actor into :attr:`log`: enough to answer a turn put
    through :func:`app.services.turns.addressed_turn` (see ``test_turns``).
    Each callable in :attr:`listeners` is called with ``(envelope, content)``
    after a message is recorded, for a test that scripts its own replies.
    """

    def __init__(
        self, records: list[TranscriptRecord] | None = None, *, reply_conf: float | None = None
    ) -> None:
        self.log = DeliveryLog(records or [])
        self.recorded: list[tuple[Any, dict[str, Any]]] = []
        self.listeners: list[Callable[[Any, dict[str, Any]], None]] = []
        self._reply_conf = reply_conf
        self._reply_seq = 0

    def record(self, envelope: Any, content: dict[str, Any], *, list_write: bool = False) -> None:
        self.recorded.append((envelope, content))
        for listener in self.listeners:
            listener(envelope, content)
        # Only exchange prompts draw a simulated reply, never the commit.
        if self._reply_conf is None or envelope.header.kind != Kind.exchange:
            return
        for actor in envelope.header.participants.actors[1:]:
            self._reply_seq += 1
            self.log.record(
                position_record(
                    actor.id, confidence=self._reply_conf, message_id=f"reply-{self._reply_seq}"
                )
            )

    def texts(self) -> list[str]:
        """The text of every message recorded, in order."""
        return [content.get("content", "") for _env, content in self.recorded]


@dataclass
class FakeManaged:
    """Stands in for ``room_channels.ManagedRoomChannel`` (the room and its log)."""

    room: str = DEFAULT_ROOM
    persister: Any = field(default_factory=FakePersister)

    async def post(self, envelope: Any, text: str, *, list_write: bool = False) -> None:
        """Mirror of ``ManagedRoomChannel.post``."""
        content = serialize_content(envelope, extra={"content": text})
        self.persister.record(envelope, content, list_write=list_write)


class FakeManager:
    """Just enough of ``RoomChannelManager`` for the engines.

    ``FakeManager(managed, members)``: a managed channel (a fresh
    :class:`FakeManaged` when omitted) and the room's roster.
    """

    def __init__(
        self, managed: FakeManaged | None = None, members: list[str] | None = None
    ) -> None:
        self._managed = managed if managed is not None else FakeManaged()
        self._members = list(members) if members is not None else ["a", "b"]
        self.opened: list[str] = []
        self.closed: list[str] = []
        self.floors: dict[str, Any] = {}
        self.floor_log: list[Any] = []

    def get(self, room: str) -> FakeManaged:
        return self._managed

    def members(self, room: str) -> list[str]:
        return list(self._members)

    def open_episode(self, room: str, episode: str, *, parties: Any = ()) -> bool:
        self.opened.append(episode)
        # Who the negotiation froze on, so a test can read back its parties.
        self.parties = sorted(parties)
        return True

    # The floor, as ``RoomChannelManager`` holds it: one per thread, and a log
    # of every hold so a test can read back whose turn each step gave.
    def hold_floor(self, room: str, episode: str, *, holder: str, speakers=()) -> Any:
        from app.services.floor import Floor

        floor = Floor(episode=episode, holder=holder, speakers=frozenset(speakers))
        self.floors[episode] = floor
        self.floor_log.append(floor)
        return floor

    def release_floor(self, room: str, episode: str) -> bool:
        return self.floors.pop(episode, None) is not None

    def floor(self, room: str, episode: str | None) -> Any:
        return self.floors.get(episode) if episode else None

    async def close_episode(self, room: str) -> bool:
        self.closed.append(room)
        return True


# ── the Pi session / LLM seam ───────────────────────────────────────────────────


def patch_pi_run(
    monkeypatch: pytest.MonkeyPatch, *, stdout: str, returncode: int = 0
) -> list[list[str]]:
    """Mock ``subprocess.run`` / ``shutil.which`` so ``PiSession`` never spawns ``pi``.

    Returns the list that captures each argv the LLM session would have executed.
    """
    from app.services import pi_session

    calls: list[list[str]] = []

    def fake_run(cmd: list[str], **_: Any) -> subprocess.CompletedProcess[str]:
        calls.append(cmd)
        return subprocess.CompletedProcess(cmd, returncode, stdout=stdout, stderr="boom")

    monkeypatch.setattr(pi_session.shutil, "which", lambda _b: "/usr/bin/pi")
    monkeypatch.setattr(pi_session.subprocess, "run", fake_run)
    return calls
