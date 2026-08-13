# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""Shared in-process fakes for the backend test suite.

One import gets you a fake coordination stack — no SLIM node, no Pi binary, no
live LLM. These used to be re-declared per test file (``_FakeChannel`` /
``_FakePersister`` / ``_FakeManager`` in ``test_aligner`` and ``test_plan_sync``,
the deterministic ``_fake_llm`` in ``test_mediator``, ``_patch_run`` in
``test_pi_brain``); this module is the single home for them.

What stands in for what:

* :class:`FakeSlimClient` / :class:`FakeSession` — the ``slim_bindings`` transport
  (``app.services.slim_client.SlimClient``), so ``room_channels`` provisioning /
  membership / channel lifecycle run without a node.
* :class:`FakeChannel` — an ``L9SlimChannel`` (``app.services.l9_slim``): records
  broadcasts and can simulate a prompted participant replying.
* :class:`FakePersister` — the transcript side of ``RoomPersister``
  (``app.services.persister``): a ``DeliveryLog`` plus ``ingest_local``.
* :class:`FakeManaged` / :class:`FakeManager` — ``ManagedRoomChannel`` /
  ``RoomChannelManager`` (``app.services.room_channels``).
* :func:`make_fake_llm` / :func:`fake_brain_factory` — the mediator's Pi brain
  seam (``brain_factory`` on ``AlignerEngine``), a deterministic prompt-keyed stub.
* :func:`patch_pi_run` — mock ``subprocess.run`` / ``shutil.which`` so ``PiBrain``
  never spawns a real ``pi``.

See ``tests/README.md`` for the "test a feature without a live stack" recipe.
"""

from __future__ import annotations

import asyncio
import json
import subprocess
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, ClassVar

from app.services import l9
from app.services.l9_models import Kind
from app.services.l9_slim import serialize_content
from app.services.persister import DeliveryLog, TranscriptRecord, record_from

if TYPE_CHECKING:
    import pytest

# The default room the simulated participant replies are stamped for. The
# mediator threads replies by message parents/recipients, not by episode URN, so
# a fake reply carrying this room's episode is read correctly even in a
# negotiation over a differently-named room (this preserves the historical
# behavior when these fakes lived in ``test_aligner``).
DEFAULT_ROOM = "align-room"
EPISODE = l9.episode_urn(DEFAULT_ROOM, "live")
TOPIC = l9.topic_urn(DEFAULT_ROOM)


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
) -> TranscriptRecord:
    """An agent-position transcript record carrying an epistemic payload."""
    data: dict[str, Any] = {"action": action}
    if confidence is not None:
        data["confidence"] = confidence
    env = l9.build_envelope(
        kind=Kind.exchange,
        episode=episode,
        sender=sender,
        sender_role=role,
        recipients=[l9.SYSTEM_ACTOR_ID],
        topic=topic,
        payload_type=payload_type,
        payload_data=data,
        message_id=message_id,
    )
    return record_from(env, serialize_content(env, extra={"content": f"{sender} position"}))


# ── L9 channel + persister (the aligner/plan-sync/mediator layer) ─────────────


class FakeChannel:
    """Records broadcasts; optionally simulates a prompted participant replying.

    Stands in for ``app.services.l9_slim.L9SlimChannel``. With ``reply_conf`` set,
    every ``exchange`` prompt draws a simulated reply from each addressed actor
    into the paired persister's log — enough to drive the SAO mediator to
    agreement node-free (see ``test_mediator``).
    """

    def __init__(
        self, persister: FakePersister | None = None, reply_conf: float | None = None
    ) -> None:
        self.sent: list[tuple[Any, dict[str, Any] | None]] = []
        self._persister = persister
        self._reply_conf = reply_conf
        self._reply_seq = 0

    async def send(self, envelope: Any, *, extra: dict[str, Any] | None = None) -> None:
        self.sent.append((envelope, extra))
        # Only exchange prompts trigger a simulated reply — never the commit.
        if self._reply_conf is None or envelope.header.kind != Kind.exchange:
            return
        assert self._persister is not None
        for actor in envelope.header.participants.actors[1:]:
            self._reply_seq += 1
            self._persister.log.record(
                position_record(
                    actor.id, confidence=self._reply_conf, message_id=f"reply-{self._reply_seq}"
                ),
                delivered_to=set(),
            )


class FakePersister:
    """The transcript side of ``RoomPersister``: a log plus ``ingest_local``."""

    def __init__(self, records: list[TranscriptRecord] | None = None) -> None:
        self.log = DeliveryLog(records or [])
        self.ingested: list[tuple[Any, dict[str, Any]]] = []

    def ingest_local(self, envelope: Any, content: dict[str, Any]) -> None:
        self.ingested.append((envelope, content))


@dataclass
class FakeManaged:
    """Stands in for ``room_channels.ManagedRoomChannel`` (room + channel state)."""

    room: str = DEFAULT_ROOM
    workspace: str = "mycelium"
    channel: Any = None
    persister: Any = None


class FakeManager:
    """Just enough of ``RoomChannelManager`` for the aligner + plan-sync consumers.

    Two construction styles are supported so the one fake serves both callers:

    * ``FakeManager(managed, members)`` — the aligner/mediator style, with an
      explicit managed channel and roster.
    * ``FakeManager(live=False)`` — the plan-sync style, which builds a default
      managed channel wrapping a fresh :class:`FakeChannel` (or ``None`` when not
      ``live``) and exposes it as ``.channel``.
    """

    def __init__(
        self,
        managed: FakeManaged | None = None,
        members: list[str] | None = None,
        *,
        live: bool = True,
    ) -> None:
        if managed is None:
            self.channel = FakeChannel()
            managed = FakeManaged(channel=self.channel) if live else None
        else:
            self.channel = getattr(managed, "channel", None)
        self._managed = managed
        self._members = list(members) if members is not None else ["a", "b"]
        self.opened: list[str] = []
        self.closed: list[str] = []

    def get(self, room: str) -> FakeManaged | None:
        return self._managed

    def members(self, room: str) -> list[str]:
        return list(self._members)

    def open_episode(self, room: str, episode: str) -> bool:
        self.opened.append(episode)
        return True

    async def close_episode(self, room: str) -> bool:
        self.closed.append(room)
        return True


# ── the SLIM transport (room_channels / slim_client layer) ────────────────────


@dataclass
class FakeSession:
    """A stand-in for a ``slim_bindings`` group session.

    Records what the moderator did to it (invites, removes, broadcasts) so
    ``room_channels`` provisioning/membership can be asserted without a node.
    """

    channel: Any = None
    published: list[bytes] = field(default_factory=list)
    invited: list[Any] = field(default_factory=list)
    removed: list[Any] = field(default_factory=list)

    async def publish_async(self, data: bytes, *_a: Any, **_k: Any) -> None:
        self.published.append(data)


class FakeSlimClient:
    """A minimal in-process stand-in for ``slim_client.SlimClient``.

    Covers both roles the real client plays:

    * **Moderator** (backend / ``room_channels``): ``connect`` → ``create_group`` →
      ``invite`` / ``remove_member`` → ``close``.
    * **Member** (a replayed inbox): ``listen_for_session`` plus the static
      ``publish`` / ``receive_message`` the durable-inbox stream sits on.

    Instance state records the lifecycle; ``inbox`` is a class-level scripted
    queue so a test can preload messages before the client is constructed (mirror
    of the CLI's ``FakeSlimClient``). Reset it per test with :meth:`reset`.
    """

    inbox: ClassVar[list[bytes]] = []
    published: ClassVar[list[bytes]] = []

    def __init__(self, identity: Any, *, secret: str | None = None) -> None:
        self.identity = identity
        self.secret = secret
        self.endpoint: str | None = None
        self.session: FakeSession | None = None
        self.closed = False

    @classmethod
    def reset(cls) -> None:
        """Clear the class-level scripted inbox/outbox (call between tests)."""
        cls.inbox = []
        cls.published = []

    async def connect(self, endpoint: str = "") -> FakeSlimClient:
        self.endpoint = endpoint
        return self

    async def create_group(self, channel: Any) -> FakeSession:
        self.session = FakeSession(channel=channel)
        return self.session

    async def invite(self, session: FakeSession, member: Any) -> None:
        session.invited.append(member)

    async def remove_member(self, session: FakeSession, member: Any) -> None:
        session.removed.append(member)

    async def listen_for_session(self) -> str:
        return "session-1"

    async def close(self) -> None:
        self.closed = True

    @staticmethod
    async def publish(session: Any, data: bytes) -> None:
        if isinstance(session, FakeSession):
            session.published.append(data)
        FakeSlimClient.published.append(data)

    @staticmethod
    async def receive_message(session: Any, *, timeout_s: float = 30.0) -> Any:
        from app.services.slim_client import SlimError

        if not FakeSlimClient.inbox:
            # Simulate a real idle window: block briefly, then report a benign
            # timeout the reconnecting stream treats as "quiet, still connected".
            await asyncio.sleep(0.02)
            raise SlimError("receive timeout")
        payload = FakeSlimClient.inbox.pop(0)

        class _Msg:
            def __init__(self, p: bytes) -> None:
                self.payload = p
                self.context = None

        return _Msg(payload)


# ── the Pi brain / LLM seam ───────────────────────────────────────────────────


def make_fake_llm() -> Any:
    """A deterministic stand-in for the mediator's Pi brain, keyed on the prompt.

    * discovery → one issue ``cap`` with three options;
    * a propose interpretation → counter to ``cap = 30``;
    * a respond interpretation → accept;
    * any broker framing → a short note.

    This is the ``brain_factory`` payload that lets the SAO mediator run
    node-free and LLM-free (see ``test_mediator``).
    """

    def _fake_llm(prompt: str, *, system: str = "", temperature: float = 0.3) -> str:
        if "identify the negotiable ISSUES" in prompt:
            return json.dumps({"issues": [{"name": "cap", "options": ["25", "30", "35"]}]})
        if "Interpret @" in prompt:
            if '"action":"counter"' in prompt:  # proposing schema
                return json.dumps({"action": "counter", "offer": {"cap": "30"}})
            return json.dumps({"action": "accept"})  # responding schema
        return "Everyone is close on the cap; let's lock 30 and move."

    return _fake_llm


def fake_brain_factory(_episode: str) -> Any:
    """A ``brain_factory`` that yields :func:`make_fake_llm` for any episode."""
    return make_fake_llm()


def patch_pi_run(
    monkeypatch: pytest.MonkeyPatch, *, stdout: str, returncode: int = 0
) -> list[list[str]]:
    """Mock ``subprocess.run`` / ``shutil.which`` so ``PiBrain`` never spawns ``pi``.

    Returns the list that captures each argv the brain would have executed.
    """
    from app.services import pi_brain

    calls: list[list[str]] = []

    def fake_run(cmd: list[str], **_: Any) -> subprocess.CompletedProcess[str]:
        calls.append(cmd)
        return subprocess.CompletedProcess(cmd, returncode, stdout=stdout, stderr="boom")

    monkeypatch.setattr(pi_brain.shutil, "which", lambda _b: "/usr/bin/pi")
    monkeypatch.setattr(pi_brain.subprocess, "run", fake_run)
    return calls
