# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""Unit tests for the SIEP aligner cognition engine (app/services/aligner.py).

Node-free: they drive the engine over fake channels/persisters so the observer
verdict, the below-threshold rejection, the driver round loop, and the
reserved-handle summon gate are all exercised as pure async logic. The live-node
observe slice is in ``test_l9_over_slim_roundtrip.py`` (guarded on a node).
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any

import pytest

from app.services import aligner, l9, l9_episode
from app.services.l9_models import Kind
from app.services.l9_slim import serialize_content
from app.services.persister import DeliveryLog, TranscriptRecord, record_from

_ROOM = "align-room"
_EPISODE = l9.episode_urn(_ROOM, "live")
_TOPIC = l9.topic_urn(_ROOM)


def _position_record(
    sender: str,
    *,
    confidence: float | None = None,
    action: str = "accept",
    role: str = "agent",
    payload_type: str = "reply",
    message_id: str | None = None,
) -> TranscriptRecord:
    """An agent-position transcript record carrying an epistemic payload."""
    data: dict[str, Any] = {"action": action}
    if confidence is not None:
        data["confidence"] = confidence
    env = l9.build_envelope(
        kind=Kind.exchange,
        episode=_EPISODE,
        sender=sender,
        sender_role=role,
        recipients=[l9.SYSTEM_ACTOR_ID],
        topic=_TOPIC,
        payload_type=payload_type,
        payload_data=data,
        message_id=message_id,
    )
    return record_from(env, serialize_content(env, extra={"content": f"{sender} position"}))


# ── fakes ────────────────────────────────────────────────────────────────────


class _FakeChannel:
    """Records broadcasts; optionally simulates a prompted participant replying."""

    def __init__(self, persister: _FakePersister | None = None, reply_conf: float | None = None):
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
                _position_record(
                    actor.id, confidence=self._reply_conf, message_id=f"reply-{self._reply_seq}"
                ),
                delivered_to=set(),
            )


class _FakePersister:
    def __init__(self, records: list[TranscriptRecord] | None = None):
        self.log = DeliveryLog(records or [])
        self.ingested: list[tuple[Any, dict[str, Any]]] = []

    def ingest_local(self, envelope: Any, content: dict[str, Any]) -> None:
        self.ingested.append((envelope, content))


@dataclass
class _FakeManaged:
    room: str
    workspace: str
    channel: Any
    persister: Any


class _FakeManager:
    def __init__(self, managed: _FakeManaged, members: list[str]):
        self._managed = managed
        self._members = members
        self.opened: list[str] = []
        self.closed: list[str] = []

    def get(self, room: str) -> _FakeManaged:
        return self._managed

    def members(self, room: str) -> list[str]:
        return list(self._members)

    def open_episode(self, room: str, episode: str) -> bool:
        self.opened.append(episode)
        return True

    async def close_episode(self, room: str) -> bool:
        self.closed.append(room)
        return True


def _engine(manager: _FakeManager, **kw: Any) -> aligner.AlignerEngine:
    kw.setdefault("handle", "aligner")
    kw.setdefault("threshold", 0.6)
    return aligner.AlignerEngine(manager, **kw)  # type: ignore[arg-type]


# ── observer mode ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_observer_emits_converged_with_correct_metrics():
    """A high-confidence seeded transcript → commit:converged with the metrics
    l9_episode.compute_metrics returns over the same positions."""
    records = [
        _position_record("agent-a", confidence=0.8, message_id="a1"),
        _position_record("agent-b", confidence=0.9, message_id="b1"),
    ]
    channel = _FakeChannel()
    persister = _FakePersister(records)
    managed = _FakeManaged(_ROOM, "mycelium", channel, persister)
    manager = _FakeManager(managed, ["agent-a", "agent-b", "aligner"])

    verdict = await _engine(manager).observe(_ROOM)

    assert verdict is not None
    assert verdict["header"]["kind"] == "commit"
    assert verdict["header"]["subkind"] == "converged"

    # Metrics match a fresh, independent replay of the same two positions.
    ep = l9_episode.open_episode(
        parent_room=_ROOM,
        short_id="live",
        workspace_id="mycelium",
        mas_id="",
        agents=["agent-a", "agent-b"],
        joined_intents="x",
    )
    l9_episode.record_reply(
        ep, handle="agent-a", reply={"action": "accept", "confidence": 0.8}, round_n=None
    )
    l9_episode.record_reply(
        ep, handle="agent-b", reply={"action": "accept", "confidence": 0.9}, round_n=None
    )
    expected = l9_episode.compute_metrics(ep)
    assert verdict["payload"]["data"]["metrics"] == expected

    # Broadcast once, and recorded once locally (drives the on_converged seam).
    assert len(channel.sent) == 1
    assert len(persister.ingested) == 1


@pytest.mark.asyncio
async def test_observer_below_threshold_emits_rejected():
    records = [
        _position_record("agent-a", confidence=0.2, message_id="a1"),
        _position_record("agent-b", confidence=0.3, message_id="b1"),
    ]
    channel = _FakeChannel()
    managed = _FakeManaged(_ROOM, "mycelium", channel, _FakePersister(records))
    manager = _FakeManager(managed, ["agent-a", "agent-b"])

    verdict = await _engine(manager).observe(_ROOM)

    assert verdict is not None
    assert verdict["header"]["subkind"] == "rejected"


@pytest.mark.asyncio
async def test_observer_ignores_human_and_engine_messages_when_scoring():
    """A human proxy message and the engine's own handle never count as a
    participant position (so they can't skew or stall the metrics)."""
    records = [
        _position_record("human", confidence=0.1, role="human", message_id="h1"),
        _position_record("aligner", confidence=0.1, message_id="al1"),
        _position_record("agent-a", confidence=0.9, message_id="a1"),
        _position_record("agent-b", confidence=0.85, message_id="b1"),
    ]
    channel = _FakeChannel()
    managed = _FakeManaged(_ROOM, "mycelium", channel, _FakePersister(records))
    manager = _FakeManager(managed, ["agent-a", "agent-b"])

    verdict = await _engine(manager).observe(_ROOM)

    assert verdict is not None
    assert verdict["header"]["subkind"] == "converged"
    # Only the two agents were scored.
    assert verdict["payload"]["data"]["metrics"]["participants"] == 2


# ── driver mode ───────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_driver_converges_and_closes_episode():
    persister = _FakePersister()
    channel = _FakeChannel(persister, reply_conf=0.9)
    managed = _FakeManaged(_ROOM, "mycelium", channel, persister)
    manager = _FakeManager(managed, ["agent-a", "agent-b", "aligner"])

    engine = _engine(manager, max_rounds=3, round_timeout_s=0.2, poll_interval_s=0.01)
    verdict = await engine.drive(_ROOM)

    assert verdict is not None
    assert verdict["header"]["subkind"] == "converged"
    # Opened an episode (frozen membership) and closed it (drains queued invites).
    # Each convening gets a unique episode id, so assert the shape, not a suffix.
    assert len(manager.opened) == 1
    assert manager.opened[0].startswith(l9.episode_urn(_ROOM, ""))
    assert manager.closed == [_ROOM]
    # Converged on round 1 → prompted the two participants exactly once each.
    prompts = [s for s, _ in channel.sent if s.header.kind == Kind.exchange]
    assert len(prompts) == 2


@pytest.mark.asyncio
async def test_driver_terminates_at_round_cap_without_replies():
    """No participant ever answers → the loop stops at the cap and rejects, never
    hanging (bounded by round_timeout_s)."""
    persister = _FakePersister()
    channel = _FakeChannel(persister, reply_conf=None)  # nobody replies
    managed = _FakeManaged(_ROOM, "mycelium", channel, persister)
    manager = _FakeManager(managed, ["agent-a", "agent-b"])

    engine = _engine(manager, max_rounds=2, round_timeout_s=0.05, poll_interval_s=0.01)
    verdict = await asyncio.wait_for(engine.drive(_ROOM), timeout=5.0)

    assert verdict is not None
    assert verdict["header"]["subkind"] == "rejected"
    assert manager.closed == [_ROOM]
    # 2 rounds x 2 participants = 4 prompts before giving up.
    prompts = [s for s, _ in channel.sent if s.header.kind == Kind.exchange]
    assert len(prompts) == 4


# ── summon routing ────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_summon_fires_only_for_the_reserved_handle():
    managed = _FakeManaged(_ROOM, "mycelium", _FakeChannel(), _FakePersister())
    engine = _engine(_FakeManager(managed, []))

    called: list[str] = []

    async def fake_mediate(
        room: str,
        engine_handle: str | None = None,
        scoped_participants: list[str] | None = None,
    ) -> None:
        called.append(room)

    engine.mediate = fake_mediate  # type: ignore[method-assign]

    def _env(sender: str) -> Any:
        return l9.build_envelope(
            kind=Kind.exchange,
            episode=_EPISODE,
            sender=sender,
            topic=_TOPIC,
            payload_type="message",
        )

    # A summon of a normal teammate does not fire the engine.
    engine.handle_summon(_ROOM, "agent-a", _env("human"))
    await asyncio.sleep(0.02)
    assert called == []

    # A summon of the reserved handle does.
    engine.handle_summon(_ROOM, "aligner", _env("human"))
    await asyncio.sleep(0.02)
    assert called == [_ROOM]

    # The engine never summons off its own message (loop guard).
    engine.handle_summon("other-room", "aligner", _env("aligner"))
    await asyncio.sleep(0.02)
    assert called == [_ROOM]


@pytest.mark.asyncio
async def test_engine_runtime_host_skips_registered_engine(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """With ENGINE_RUNTIME=host the backend must NOT mediate a *registered* engine
    (the host daemon owns the run) — but the reserved handle still runs backend-side."""
    import yaml

    from app.config import settings
    from app.services.filesystem import get_room_dir, write_memory_file

    room = "host-runtime-room"
    write_memory_file(
        get_room_dir(room),
        "agents/mediator-1",
        yaml.safe_dump({"adapter": "engine", "kind": "aligner"}),
        created_by="cli-user",
    )

    managed = _FakeManaged(room, "mycelium", _FakeChannel(), _FakePersister())
    engine = _engine(_FakeManager(managed, []))
    called: list[str] = []

    async def fake_mediate(
        r: str,
        engine_handle: str | None = None,
        scoped_participants: list[str] | None = None,
    ) -> None:
        called.append(r)

    engine.mediate = fake_mediate  # type: ignore[method-assign]
    monkeypatch.setattr(settings, "ENGINE_RUNTIME", "host")

    def _env(sender: str) -> Any:
        return l9.build_envelope(
            kind=Kind.exchange,
            episode=_EPISODE,
            sender=sender,
            topic=_TOPIC,
            payload_type="message",
        )

    # The registered engine is skipped — the host daemon drives it.
    engine.handle_summon(room, "mediator-1", _env("human"))
    await asyncio.sleep(0.02)
    assert called == []

    # The reserved handle has no host manifest, so it always runs backend-side.
    engine.handle_summon(room, "aligner", _env("human"))
    await asyncio.sleep(0.02)
    assert called == [room]


def test_registered_engine_kind_reads_manifest() -> None:
    """A summon fires the aligner for a registered ``engine`` (kind aligner), not
    for a normal agent or a handle with no manifest — the engine-reframe gate."""
    import yaml

    from app.services.aligner import _registered_engine_kind
    from app.services.filesystem import get_room_dir, write_memory_file

    room = "engine-room"
    room_dir = get_room_dir(room)

    def _seed(handle: str, body: dict) -> None:
        write_memory_file(room_dir, f"agents/{handle}", yaml.safe_dump(body), created_by="cli-user")

    _seed("mediator-1", {"adapter": "engine", "kind": "aligner"})
    _seed("worker-1", {"adapter": "claude_code", "cwd": "/tmp"})

    assert _registered_engine_kind(room, "mediator-1") == "aligner"
    assert _registered_engine_kind(room, "worker-1") is None  # a normal agent
    assert _registered_engine_kind(room, "ghost") is None  # no manifest


def test_at_mention_neutralized_in_mediator_prompt() -> None:
    """The mediator strips ``@`` before a word so its broker summary (which names
    the other agents) can't spuriously wake them — only the L9 recipient wakes."""
    from app.services.aligner import _AT_MENTION

    text = "@growth holds tech at 40%; @risk wants a hard cap. Email @ home is fine."
    out = _AT_MENTION.sub("", text)
    assert "@growth" not in out and "@risk" not in out
    assert "growth holds tech" in out and "risk wants" in out
    assert "@ home" in out  # a lone @ (not before a word char) is untouched
