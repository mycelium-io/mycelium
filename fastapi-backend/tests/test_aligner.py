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
from typing import Any

import pytest

from app.services import aligner, l9
from app.services.l9_models import Kind
from tests.fakes import FakeChannel, FakeManaged, FakeManager, FakePersister

_ROOM = "align-room"
_EPISODE = l9.episode_urn(_ROOM, "live")
_TOPIC = l9.topic_urn(_ROOM)


def _engine(manager: FakeManager, **kw: Any) -> aligner.AlignerEngine:
    kw.setdefault("handle", "aligner")
    kw.setdefault("threshold", 0.6)
    return aligner.AlignerEngine(manager, **kw)  # type: ignore[arg-type]


# ── summon routing ────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_summon_fires_only_for_the_reserved_handle():
    managed = FakeManaged(_ROOM, "mycelium", FakeChannel(), FakePersister())
    engine = _engine(FakeManager(managed, []))

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
async def test_mediate_explains_when_too_few_participants():
    """Summoned with fewer than two participants, the aligner posts a
    brain-authored explanation to the room instead of silently opening and
    rejecting a throwaway episode."""
    channel = FakeChannel()
    persister = FakePersister()
    managed = FakeManaged(_ROOM, "mycelium", channel, persister)
    manager = FakeManager(managed, ["solo"])  # one participant besides the aligner
    engine = _engine(
        manager,
        brain_factory=lambda _ep: (lambda _prompt, **_kw: "Post positions first, then summon me."),
    )

    result = await engine.mediate(_ROOM)

    assert result is None
    assert manager.opened == []  # no throwaway episode opened
    # The aligner broadcast its explanation to the room ...
    assert len(channel.sent) == 1
    env, extra = channel.sent[0]
    assert env.header.kind == Kind.exchange
    assert extra is not None and extra["content"] == "Post positions first, then summon me."
    # ... and recorded it locally so the transcript / UI see it.
    assert persister.ingested
    assert persister.ingested[-1][1]["content"] == "Post positions first, then summon me."


@pytest.mark.asyncio
async def test_mediate_stall_falls_back_when_brain_unavailable():
    """If the brain errors, the aligner still leaves a static, actionable reply
    rather than saying nothing."""
    channel = FakeChannel()
    persister = FakePersister()
    managed = FakeManaged(_ROOM, "mycelium", channel, persister)

    def _boom(_ep: str) -> Any:
        def _raise(_prompt: str, **_kw: Any) -> str:
            raise RuntimeError("no pi")

        return _raise

    engine = _engine(FakeManager(managed, []), brain_factory=_boom)  # zero participants

    await engine.mediate(_ROOM)

    assert len(channel.sent) == 1
    _, extra = channel.sent[0]
    assert extra is not None and "at least two agents" in extra["content"]


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

    managed = FakeManaged(room, "mycelium", FakeChannel(), FakePersister())
    engine = _engine(FakeManager(managed, []))
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
