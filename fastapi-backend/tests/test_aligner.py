# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""Unit tests for the SIEP aligner cognition engine (app/services/aligner.py).

Node-free: they drive the engine over fake channels/persisters so the observer
verdict, the below-threshold rejection, the driver round loop, and the
reserved-handle summon gate are all exercised as pure async logic. The live-node
observe slice is in ``test_message_over_slim_roundtrip.py`` (guarded on a node).
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from app.services import aligner, message_format
from app.services.message_models import Kind
from tests.fakes import FakeChannel, FakeManaged, FakeManager, FakePersister

_ROOM = "align-room"
_EPISODE = message_format.episode_urn(_ROOM, "live")
_TOPIC = message_format.topic_urn(_ROOM)


def _engine(manager: FakeManager, **kw: Any) -> aligner.AlignerEngine:
    kw.setdefault("handle", "aligner")
    kw.setdefault("threshold", 0.6)
    return aligner.AlignerEngine(manager, **kw)  # type: ignore[arg-type]


# ── summon routing ────────────────────────────────────────────────────────────


def _add_aligner(room: str, handle: str = "aligner") -> None:
    """Add an aligner to ``room``, as `mycelium engine create --kind aligner` does."""
    import yaml

    from app.services.filesystem import get_room_dir, write_memory_file

    write_memory_file(
        get_room_dir(room),
        f"agents/{handle}",
        yaml.safe_dump({"adapter": "engine", "kind": "aligner"}),
        created_by="cli-user",
    )


def _summon_env(sender: str, room: str) -> Any:
    """A summon posted in ``room``'s own channel."""
    return message_format.build_envelope(
        kind=Kind.exchange,
        episode=message_format.live_episode_urn(room),
        sender=sender,
        topic=message_format.topic_urn(room),
        payload_type="message",
    )


def _recording(engine: aligner.AlignerEngine) -> list[tuple[str, list[str] | None]]:
    """Swap the engine's run for a recorder of (room, parties)."""
    called: list[tuple[str, list[str] | None]] = []

    async def fake_mediate(
        room: str,
        engine_handle: str | None = None,
        scoped_participants: list[str] | None = None,
        **_kw: object,
    ) -> None:
        called.append((room, scoped_participants))

    engine.mediate = fake_mediate  # type: ignore[method-assign]
    return called


@pytest.mark.asyncio
async def test_a_mention_in_a_room_without_an_aligner_starts_nothing_and_says_so_once():
    """No aligner registered, no run: the mention used to fall back to a built-in
    aligner every room had, which is how a room nobody added one to got a run."""
    room = "no-aligner-room"
    channel = FakeChannel()
    managed = FakeManaged(room, "mycelium", channel, FakePersister())
    engine = _engine(FakeManager(managed, ["a", "b"]))
    called = _recording(engine)

    for _ in range(2):
        engine.handle_summon(room, "aligner", _summon_env("julia", room), ["aligner", "a", "b"])
        await asyncio.sleep(0.02)

    assert called == []
    said = [extra["content"] for _env, extra in channel.sent if extra]
    assert len(said) == 1
    assert "no aligner in this room" in said[0]
    assert f"mycelium engine create aligner --kind aligner --room {room}" in said[0]


@pytest.mark.asyncio
async def test_a_registered_aligner_runs_with_the_members_named():
    room = "named-room"
    _add_aligner(room)
    managed = FakeManaged(room, "mycelium", FakeChannel(), FakePersister())
    engine = _engine(FakeManager(managed, ["a", "b", "reviewer"]))
    called = _recording(engine)

    # A mention of a teammate doesn't start the aligner.
    engine.handle_summon(room, "a", _summon_env("julia", room), ["a"])
    await asyncio.sleep(0.02)
    assert called == []

    engine.handle_summon(room, "aligner", _summon_env("julia", room), ["aligner", "a", "b"])
    await asyncio.sleep(0.02)
    # Only who was named: the reviewer present in the room isn't a party.
    assert called == [(room, ["a", "b"])]

    # Never off its own message.
    engine.handle_summon(room, "aligner", _summon_env("aligner", room), ["aligner", "a", "b"])
    await asyncio.sleep(0.02)
    assert len(called) == 1


@pytest.mark.asyncio
async def test_a_summon_in_the_room_that_names_nobody_starts_nothing():
    """In the room, everyone present is not who should agree: it asks for names."""
    room = "unnamed-room"
    _add_aligner(room)
    channel = FakeChannel()
    managed = FakeManaged(room, "mycelium", channel, FakePersister())
    engine = _engine(FakeManager(managed, ["a", "b"]))
    called = _recording(engine)

    engine.handle_summon(room, "aligner", _summon_env("julia", room), ["aligner"])
    await asyncio.sleep(0.02)

    assert called == []
    said = [extra["content"] for _env, extra in channel.sent if extra]
    assert said and "Mention the members who should agree" in said[0]


@pytest.mark.asyncio
async def test_a_summon_negotiates_in_the_thread_it_was_made_in():
    """The thread the summon was posted in is where the negotiation is held, so
    an agent answers the aligner with the same flags as anything else said
    there; a summon in the room is held in the room."""
    _add_aligner(_ROOM)
    managed = FakeManaged(_ROOM, "mycelium", FakeChannel(), FakePersister())
    engine = _engine(FakeManager(managed, []))
    held_in: list[str | None] = []

    async def fake_mediate(room: str, episode: str | None = None, **_kwargs: object) -> None:
        held_in.append(episode)

    engine.mediate = fake_mediate  # type: ignore[method-assign]
    thread = message_format.episode_urn(_ROOM, "t3aa11bb")
    for where in (thread, message_format.live_episode_urn(_ROOM)):
        summon = message_format.build_envelope(
            kind=Kind.exchange, episode=where, sender="human", topic=_TOPIC, payload_type="message"
        )
        engine.handle_summon(_ROOM, "aligner", summon, ["aligner", "a", "b"])
        await asyncio.sleep(0.02)
    assert held_in == [thread, message_format.live_episode_urn(_ROOM)]


@pytest.mark.asyncio
async def test_mediate_explains_when_too_few_participants():
    """Summoned with fewer than two participants, the aligner posts a
    LLM-authored explanation to the room instead of silently opening and
    rejecting a throwaway episode."""
    channel = FakeChannel()
    persister = FakePersister()
    managed = FakeManaged(_ROOM, "mycelium", channel, persister)
    manager = FakeManager(managed, ["solo"])  # one participant besides the aligner
    engine = _engine(
        manager,
        llm_session_factory=lambda _ep: (
            lambda _prompt, **_kw: "Post positions first, then summon me."
        ),
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
    """If the LLM session errors, the aligner still leaves a static, actionable reply
    rather than saying nothing."""
    channel = FakeChannel()
    persister = FakePersister()
    managed = FakeManaged(_ROOM, "mycelium", channel, persister)

    def _boom(_ep: str) -> Any:
        def _raise(_prompt: str, **_kw: Any) -> str:
            raise RuntimeError("no pi")

        return _raise

    engine = _engine(FakeManager(managed, []), llm_session_factory=_boom)  # zero participants

    await engine.mediate(_ROOM)

    assert len(channel.sent) == 1
    _, extra = channel.sent[0]
    assert extra is not None and "at least two agents" in extra["content"]


@pytest.mark.asyncio
async def test_engine_runtime_host_skips_registered_engine(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """With ENGINE_RUNTIME=host the backend must NOT mediate a registered engine
    (the host daemon owns the run)."""
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
        **_kwargs: object,
    ) -> None:
        called.append(r)

    engine.mediate = fake_mediate  # type: ignore[method-assign]
    monkeypatch.setattr(settings, "ENGINE_RUNTIME", "host")

    def _env(sender: str) -> Any:
        return message_format.build_envelope(
            kind=Kind.exchange,
            episode=_EPISODE,
            sender=sender,
            topic=_TOPIC,
            payload_type="message",
        )

    # The registered engine is skipped — the host daemon drives it.
    engine.handle_summon(room, "mediator-1", _env("human"), ["mediator-1", "a", "b"])
    await asyncio.sleep(0.02)
    assert called == []


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


def test_the_mediator_is_told_a_bare_mention_asks() -> None:
    """What the aligner posts is posted as written, so its model is told what a
    bare ``@`` does, the same as every member the hub plays."""
    import inspect

    from app.services import mediator
    from app.services.asks import MENTION_ETIQUETTE

    assert "MENTION_ETIQUETTE" in inspect.getsource(mediator)
    assert "@~name" in MENTION_ETIQUETTE


# ── move type reaches the wire ─────────────────────────────────────────────


def _fold_episode() -> Any:
    from app.services import episode_state

    return episode_state.open_episode(
        parent_room=_ROOM,
        short_id="abc123",
        workspace_id="ws-1",
        mas_id="mas-1",
        agents=["a1", "a2"],
        joined_intents="- a1: ship\n- a2: test",
        engine_handle="aligner",
    )


def _last_subkind(ep: Any) -> str | None:
    return ep.messages[-1]["header"].get("subkind")


def test_fold_reading_stamps_move_subkind() -> None:
    """The mediator's interpreted move survives to the reply envelope's subkind
    instead of being collapsed away — a proposer's offer is a ``counter``, a
    responder's verdict is ``accept``/``reject``."""
    engine = _engine(
        FakeManager(FakeManaged(_ROOM, "mycelium", FakeChannel(), FakePersister()), [])
    )

    # Responder accept / reject map straight through.
    ep = _fold_episode()
    engine._fold_reading(ep, "a1", {"action": "accept"}, proposing=False)
    assert _last_subkind(ep) == "accept"
    engine._fold_reading(ep, "a1", {"action": "reject"}, proposing=False)
    assert _last_subkind(ep) == "reject"

    # A proposer's offer is a counter even though the metric action folds to accept.
    ep = _fold_episode()
    engine._fold_reading(
        ep, "a1", {"action": "counter", "offer": {"budget": "high"}}, proposing=True
    )
    assert _last_subkind(ep) == "counter"

    # A bare offer with no explicit verb still reads as a counter.
    ep = _fold_episode()
    engine._fold_reading(ep, "a1", {"offer": {"budget": "low"}}, proposing=True)
    assert _last_subkind(ep) == "counter"


# ── activity signal ───────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_every_pi_call_is_bracketed_by_the_activity_signal():
    """The room sees "@aligner is responding…" for exactly the span of a Pi
    call — raised from the loop even though the mediator calls the session off
    a worker thread — and never as a message (#513)."""
    from app.bus import bus, room_channel
    from app.services import activity

    channel = FakeChannel()
    persister = FakePersister()
    managed = FakeManaged(_ROOM, "mycelium", channel, persister)
    manager = FakeManager(managed, ["solo"])  # the too-few-participants path: one Pi call
    engine = _engine(
        manager,
        llm_session_factory=lambda _ep: lambda _prompt, **_kw: "Post positions first.",
    )

    queue = bus.subscribe(room_channel(_ROOM))
    try:
        await engine.mediate(_ROOM)
        await asyncio.sleep(0)  # let the thread-safe callbacks land on the loop
        frames = []
        while not queue.empty():
            frames.append(queue.get_nowait())
    finally:
        bus.unsubscribe(room_channel(_ROOM), queue)

    signals = [f for f in frames if f.get("type") == activity.ACTIVITY_TYPE]
    assert [f["state"] for f in signals] == ["responding", "done"]
    assert all(f["handle"] == "aligner" for f in signals)
    assert all(f["room_name"] == _ROOM for f in signals)
    # The signal is not a line in the room: the one broadcast is the explanation.
    assert len(channel.sent) == 1


@pytest.mark.asyncio
async def test_a_failing_pi_call_still_ends_its_signal():
    """A Pi turn that raises must not leave "@aligner is responding…" standing."""
    from app.bus import bus, room_channel
    from app.services import activity

    channel = FakeChannel()
    managed = FakeManaged(_ROOM, "mycelium", channel, FakePersister())

    def _boom(_ep: str) -> Any:
        def _raise(_prompt: str, **_kw: Any) -> str:
            raise RuntimeError("no pi")

        return _raise

    engine = _engine(FakeManager(managed, []), llm_session_factory=_boom)
    queue = bus.subscribe(room_channel(_ROOM))
    try:
        await engine.mediate(_ROOM)
        await asyncio.sleep(0)
        states = []
        while not queue.empty():
            frame = queue.get_nowait()
            if frame.get("type") == activity.ACTIVITY_TYPE:
                states.append(frame["state"])
    finally:
        bus.unsubscribe(room_channel(_ROOM), queue)

    assert states == ["responding", "done"]


# ── the roster the mediator brokers between ──────────────────────────────────


def _register(room: str, handle: str, **manifest: object) -> None:
    """Write an ``agents/<handle>`` manifest, the way `agent create` does."""
    import yaml

    from app.services.filesystem import get_room_dir, write_memory_file

    body = yaml.safe_dump({"adapter": "claude_code", **manifest})
    write_memory_file(get_room_dir(room), f"agents/{handle}", body, created_by="test")


def test_roster_is_the_registered_agents_not_who_is_connected(tmp_path, monkeypatch) -> None:
    """The regression this exists for: agents parked in herdr panes (or simply
    between turns) hold no SLIM socket and no lease, so ``manager.members()``
    reports an empty room while ``agent ls`` shows a full one. Brokering is not
    delivery, so the roster must come from the registry, not from connectivity —
    otherwise a summon in a herdr-only room could never reach two participants.
    """
    monkeypatch.setenv("MYCELIUM_DATA_DIR", str(tmp_path))
    room = "roster-room"
    _register(room, "reviewer")
    _register(room, "pm")

    managed = FakeManaged(room, "mycelium", FakeChannel(), FakePersister())
    engine = _engine(FakeManager(managed, []))  # nobody connected at all

    assert engine._roster(room, "aligner") == ["pm", "reviewer"]


def test_roster_keeps_a_connected_agent_that_was_never_registered(tmp_path, monkeypatch) -> None:
    """`await`/`respond` join a room without `agent create`, so the registry is
    not the whole story either — the roster is the union of both."""
    monkeypatch.setenv("MYCELIUM_DATA_DIR", str(tmp_path))
    room = "union-room"
    _register(room, "reviewer")

    managed = FakeManaged(room, "mycelium", FakeChannel(), FakePersister())
    engine = _engine(FakeManager(managed, ["ad-hoc", "reviewer"]))  # one has no manifest

    assert engine._roster(room, "aligner") == ["ad-hoc", "reviewer"]


def test_roster_excludes_engines_and_the_summoned_handle(tmp_path, monkeypatch) -> None:
    """An engine is never a party to the deal it brokers."""
    monkeypatch.setenv("MYCELIUM_DATA_DIR", str(tmp_path))
    room = "engine-room"
    _register(room, "reviewer")
    _register(room, "aligner", adapter="engine", kind="aligner")
    _register(room, "synthesizer", adapter="engine", kind="synthesizer")

    managed = FakeManaged(room, "mycelium", FakeChannel(), FakePersister())
    engine = _engine(FakeManager(managed, []))

    assert engine._roster(room, "aligner") == ["reviewer"]


def test_a_persona_or_worker_the_summon_names_is_a_party(tmp_path, monkeypatch) -> None:
    """A persona or a worker plays a teammate: `@aligner @finance @sales` puts
    them in the deal. Unnamed, they stay out, and a named non-teammate engine
    is never a party."""
    monkeypatch.setenv("MYCELIUM_DATA_DIR", str(tmp_path))
    room = "teammate-room"
    _register(room, "reviewer")
    _register(room, "finance", adapter="engine", kind="persona")
    _register(room, "builder", adapter="engine", kind="worker")
    _register(room, "synthesizer", adapter="engine", kind="synthesizer")

    managed = FakeManaged(room, "mycelium", FakeChannel(), FakePersister())
    engine = _engine(FakeManager(managed, []))

    named = ["finance", "builder", "synthesizer"]
    assert engine._roster(room, "aligner", named=named) == ["builder", "finance", "reviewer"]
    assert engine._roster(room, "aligner") == ["reviewer"]
