# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""Unit tests for the synthesizer cognition engine (app/services/synthesizer.py).

Node-free: the Pi turn is patched, so these exercise the summon gate, the
read → distill → write path, the incremental cursor, the type-based corpus read,
the exclusion of the engine's own posts, and the fail-soft behavior — all as pure
async logic against a temp ``.mycelium`` dir.
"""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
import yaml

from app.services import l9, memory_sync, persister, synthesizer
from app.services.filesystem import get_room_dir, read_memory_file, write_memory_file
from app.services.l9_models import Kind
from app.services.l9_slim import serialize_content
from tests.fakes import FakeChannel, FakeManaged, FakeManager, FakePersister

_ROOM = "synth-room"
_EPISODE = l9.episode_urn(_ROOM, "live")
_TOPIC = l9.topic_urn(_ROOM)
_T0 = datetime(2026, 8, 20, 12, 0, tzinfo=UTC)


def _engine() -> synthesizer.SynthesizerEngine:
    managed = FakeManaged(_ROOM, "mycelium", FakeChannel(), FakePersister())
    return synthesizer.SynthesizerEngine(FakeManager(managed, []))  # type: ignore[arg-type]


def _env(sender: str) -> Any:
    return l9.build_envelope(
        kind=Kind.exchange,
        episode=_EPISODE,
        sender=sender,
        topic=_TOPIC,
        payload_type="message",
    )


# ── transcript seeding ────────────────────────────────────────────────────────


def _chat(room: str, message_id: str, *, sender: str, text: str, at: datetime) -> None:
    """Append one plain chat message to the room's durable transcript."""
    env = l9.build_envelope(
        kind=Kind.exchange,
        episode=_EPISODE,
        sender=sender,
        recipients=[l9.SYSTEM_ACTOR_ID],
        topic=_TOPIC,
        message_id=message_id,
        payload_type="message",
    )
    record = persister.record_from(env, serialize_content(env, extra={"content": text}))
    record.recorded_at = at.isoformat()
    persister.append_transcript(room, record)


def _knowledge(room: str, message_id: str, *, at: datetime) -> None:
    """Append a ``knowledge`` memory-push record — a promoted L9 frame whose
    projected content is a serialized envelope, not prose."""
    write = memory_sync.KnowledgeWrite(
        key="decisions/db",
        content="PostgreSQL chosen.",
        version=1,
        created_by="agent-a",
        updated_by="agent-a",
        updated_at=at.isoformat(),
    )
    env = memory_sync.build_knowledge_envelope(
        room=room,
        write=write,
        recipients=[l9.SYSTEM_ACTOR_ID],
        subkind=memory_sync.MEMORY_WRITE_SUBKIND,
    )
    record = persister.record_from(
        env, serialize_content(env, extra={"content": "memory updated → decisions/db"})
    )
    record.message_id = message_id
    record.recorded_at = at.isoformat()
    persister.append_transcript(room, record)


def _seed_chat(room: str) -> None:
    _chat(room, "m-1", sender="agent-a", text="I think we should use PostgreSQL.", at=_T0)
    _chat(
        room,
        "m-2",
        sender="agent-b",
        text="Agreed — vector search settles it.",
        at=_T0 + timedelta(minutes=1),
    )


def _seed_memories(room: str) -> None:
    write_memory_file(
        get_room_dir(room),
        "decisions/db",
        "PostgreSQL chosen for graph+SQL+vector support.",
        created_by="agent-a",
    )
    write_memory_file(
        get_room_dir(room),
        "status/current",
        "Backend scaffolding underway; API not yet wired.",
        created_by="agent-b",
    )


def _register_synthesizer(room: str, handle: str) -> None:
    write_memory_file(
        get_room_dir(room),
        f"agents/{handle}",
        yaml.safe_dump({"adapter": "engine", "kind": "synthesizer"}),
        created_by="cli-user",
    )


@pytest.fixture(autouse=True)
def _fast_embed(monkeypatch: pytest.MonkeyPatch) -> None:
    """Skip the ONNX embedding model — the write path is what we're testing."""
    monkeypatch.setattr("app.routes.memory.embed_text", lambda _text: [0.0])


@pytest.fixture(autouse=True)
def _messages_source(monkeypatch: pytest.MonkeyPatch) -> None:
    """Pin the default corpus; the memory-source tests opt back out."""
    from app.config import settings

    monkeypatch.setattr(settings, "SYNTHESIZER_SOURCE", "messages")


# ── the read → distill → write path ────────────────────────────────────────────


@pytest.mark.asyncio
async def test_synthesize_distills_the_transcript(monkeypatch: pytest.MonkeyPatch) -> None:
    _seed_chat(_ROOM)
    # Memory exists too — and must not be what gets summarized.
    _seed_memories(_ROOM)
    seen_prompt: list[str] = []

    def fake_pi(prompt: str, _timeout: float, _room: str = "") -> str:
        seen_prompt.append(prompt)
        return "# Room briefing\n\n- DB: PostgreSQL"

    monkeypatch.setattr(synthesizer, "_pi_complete", fake_pi)

    result = await _engine().synthesize(_ROOM)

    assert result is not None
    assert "Room briefing" in result
    written = read_memory_file(get_room_dir(_ROOM), synthesizer.SYNTHESIS_KEY)
    assert written is not None
    meta, body = written
    assert "Room briefing" in body
    # The corpus is what was said, tagged by speaker.
    assert "@agent-a: I think we should use PostgreSQL." in seen_prompt[0]
    assert "Agreed — vector search settles it." in seen_prompt[0]
    # …not the memory store.
    assert "scaffolding" not in seen_prompt[0]
    # The cursor landed with the summary, in the same write.
    assert meta[synthesizer.CURSOR_META_KEY]["message_id"]


@pytest.mark.asyncio
async def test_a_second_run_distills_only_what_is_new(monkeypatch: pytest.MonkeyPatch) -> None:
    _seed_chat(_ROOM)
    prompts: list[str] = []
    monkeypatch.setattr(
        synthesizer, "_pi_complete", lambda p, _t, _r="": prompts.append(p) or "first briefing"
    )
    engine = _engine()

    await engine.synthesize(_ROOM)

    _chat(_ROOM, "m-3", sender="agent-a", text="Ship it Friday.", at=_T0 + timedelta(minutes=5))
    monkeypatch.setattr(
        synthesizer, "_pi_complete", lambda p, _t, _r="": prompts.append(p) or "second briefing"
    )
    await engine.synthesize(_ROOM)

    second = prompts[1]
    assert "Ship it Friday." in second
    # Already-distilled turns are not re-read…
    assert "I think we should use PostgreSQL." not in second
    # …they are carried as the standing briefing to fold into.
    assert "first briefing" in second
    written = read_memory_file(get_room_dir(_ROOM), synthesizer.SYNTHESIS_KEY)
    assert written is not None
    assert written[0]["version"] == 2
    assert "second briefing" in written[1]


@pytest.mark.asyncio
async def test_rerunning_with_nothing_new_writes_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    _seed_chat(_ROOM)
    monkeypatch.setattr(synthesizer, "_pi_complete", lambda _p, _t, _r="": "briefing")
    engine = _engine()
    await engine.synthesize(_ROOM)

    def boom(_p: str, _t: float, _r: str = "") -> str:
        raise AssertionError("Pi must not run when there is nothing new")

    monkeypatch.setattr(synthesizer, "_pi_complete", boom)

    assert await engine.synthesize(_ROOM) is None
    written = read_memory_file(get_room_dir(_ROOM), synthesizer.SYNTHESIS_KEY)
    assert written is not None
    assert written[0]["version"] == 1  # no duplicate version, no re-summarized text


@pytest.mark.asyncio
async def test_full_pass_re_reads_the_whole_transcript(monkeypatch: pytest.MonkeyPatch) -> None:
    _seed_chat(_ROOM)
    prompts: list[str] = []
    monkeypatch.setattr(
        synthesizer, "_pi_complete", lambda p, _t, _r="": prompts.append(p) or "briefing"
    )
    engine = _engine()
    await engine.synthesize(_ROOM)

    await engine.synthesize(_ROOM, full=True)

    assert "I think we should use PostgreSQL." in prompts[1]


@pytest.mark.asyncio
async def test_the_engines_own_posts_never_feed_the_next_run(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The synthesizer says its briefing into the room, so it lands in its own
    input. A second run must not feed on the first."""
    _register_synthesizer(_ROOM, "synth-1")
    _seed_chat(_ROOM)
    prompts: list[str] = []
    monkeypatch.setattr(
        synthesizer, "_pi_complete", lambda p, _t, _r="": prompts.append(p) or "BRIEFING TEXT"
    )
    engine = _engine()

    await engine.synthesize(_ROOM, engine_handle="synth-1")
    # What ``_say`` posts, recorded to the transcript the way the persister would.
    _chat(
        _ROOM,
        "m-say",
        sender="synth-1",
        text="BRIEFING TEXT",
        at=_T0 + timedelta(minutes=2),
    )
    _chat(_ROOM, "m-3", sender="agent-b", text="One more thing.", at=_T0 + timedelta(minutes=3))

    await engine.synthesize(_ROOM, engine_handle="synth-1")

    second = prompts[1]
    assert "One more thing." in second
    assert "@synth-1:" not in second
    # The briefing is present only as the carried standing summary, never as a
    # transcript line the engine reads back as someone's contribution.
    assert second.count("BRIEFING TEXT") == 1
    assert "STANDING BRIEFING" in second


@pytest.mark.asyncio
async def test_system_frames_never_reach_the_prompt(monkeypatch: pytest.MonkeyPatch) -> None:
    """A ``knowledge`` push projects as an ``l9_knowledge`` frame whose content is
    a serialized envelope. Reading by type keeps it out of the corpus."""
    _knowledge(_ROOM, "k-1", at=_T0)
    _chat(_ROOM, "m-1", sender="agent-a", text="Plain prose.", at=_T0 + timedelta(minutes=1))
    prompts: list[str] = []
    monkeypatch.setattr(
        synthesizer, "_pi_complete", lambda p, _t, _r="": prompts.append(p) or "briefing"
    )

    result = await _engine().synthesize(_ROOM)

    assert result is not None
    assert "Plain prose." in prompts[0]
    assert '"l9"' not in prompts[0]
    assert "memory updated" not in prompts[0]
    body = read_memory_file(get_room_dir(_ROOM), synthesizer.SYNTHESIS_KEY)
    assert body is not None
    assert '"l9"' not in body[1]


@pytest.mark.asyncio
async def test_synthesize_noop_on_a_silent_room(monkeypatch: pytest.MonkeyPatch) -> None:
    get_room_dir(_ROOM).mkdir(parents=True, exist_ok=True)  # exists but nobody spoke
    _seed_memories(_ROOM)  # memory alone is not a reason to run

    def boom(_p: str, _t: float, _r: str = "") -> str:
        raise AssertionError("Pi must not run for a room with no conversation")

    monkeypatch.setattr(synthesizer, "_pi_complete", boom)

    assert await _engine().synthesize(_ROOM) is None
    assert read_memory_file(get_room_dir(_ROOM), synthesizer.SYNTHESIS_KEY) is None


@pytest.mark.asyncio
async def test_synthesize_failsoft_on_pi_error(monkeypatch: pytest.MonkeyPatch) -> None:
    _seed_chat(_ROOM)

    def boom(_p: str, _t: float, _r: str = "") -> str:
        raise RuntimeError("pi exploded")

    monkeypatch.setattr(synthesizer, "_pi_complete", boom)

    # No exception escapes, no partial summary is written, the cursor holds.
    assert await _engine().synthesize(_ROOM) is None
    assert read_memory_file(get_room_dir(_ROOM), synthesizer.SYNTHESIS_KEY) is None


# ── the memory corpus, now behind SYNTHESIZER_SOURCE ───────────────────────────


@pytest.mark.asyncio
async def test_memory_source_summarizes_the_store(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.config import settings

    monkeypatch.setattr(settings, "SYNTHESIZER_SOURCE", "memory")
    _seed_memories(_ROOM)
    _seed_chat(_ROOM)
    seen_prompt: list[str] = []
    monkeypatch.setattr(
        synthesizer, "_pi_complete", lambda p, _t, _r="": seen_prompt.append(p) or "ok"
    )

    assert await _engine().synthesize(_ROOM) is not None

    assert "PostgreSQL chosen" in seen_prompt[0]
    assert "scaffolding" in seen_prompt[0]
    # Nothing incremental about this path — no cursor is claimed.
    written = read_memory_file(get_room_dir(_ROOM), synthesizer.SYNTHESIS_KEY)
    assert written is not None
    assert synthesizer.CURSOR_META_KEY not in written[0]


@pytest.mark.asyncio
async def test_memory_source_excludes_manifests_and_prior_summary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.config import settings

    monkeypatch.setattr(settings, "SYNTHESIZER_SOURCE", "memory")
    _seed_memories(_ROOM)
    _register_synthesizer(_ROOM, "synth-1")
    write_memory_file(
        get_room_dir(_ROOM),
        synthesizer.SYNTHESIS_KEY,
        "STALE PRIOR SUMMARY",
        created_by="synthesizer",
    )
    seen_prompt: list[str] = []
    monkeypatch.setattr(
        synthesizer, "_pi_complete", lambda p, _t, _r="": seen_prompt.append(p) or "ok"
    )

    await _engine().synthesize(_ROOM)

    assert "adapter: engine" not in seen_prompt[0]
    assert "STALE PRIOR SUMMARY" not in seen_prompt[0]


@pytest.mark.asyncio
async def test_memory_source_noop_on_empty_room(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.config import settings

    monkeypatch.setattr(settings, "SYNTHESIZER_SOURCE", "memory")
    get_room_dir(_ROOM).mkdir(parents=True, exist_ok=True)

    def boom(_p: str, _t: float, _r: str = "") -> str:
        raise AssertionError("Pi must not run for an empty room")

    monkeypatch.setattr(synthesizer, "_pi_complete", boom)

    assert await _engine().synthesize(_ROOM) is None
    assert read_memory_file(get_room_dir(_ROOM), synthesizer.SYNTHESIS_KEY) is None


# ── the summon gate ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_summon_fires_only_for_a_registered_synthesizer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Pin backend runtime — the host path is covered separately, and the local
    # ``~/.mycelium/.env`` may default this to ``host``.
    from app.config import settings

    monkeypatch.setattr(settings, "ENGINE_RUNTIME", "backend")
    _register_synthesizer(_ROOM, "synth-1")
    write_memory_file(
        get_room_dir(_ROOM),
        "agents/mediator-1",
        yaml.safe_dump({"adapter": "engine", "kind": "aligner"}),
        created_by="cli-user",
    )
    engine = _engine()
    called: list[str] = []

    async def fake_synthesize(
        room: str, engine_handle: str | None = None, directive: str = "", full: bool = False
    ) -> None:
        called.append(engine_handle or "?")

    engine.synthesize = fake_synthesize  # type: ignore[method-assign]

    # A normal teammate: no fire.
    engine.handle_summon(_ROOM, "agent-a", _env("human"))
    # The aligner engine: not ours — no fire.
    engine.handle_summon(_ROOM, "mediator-1", _env("human"))
    await asyncio.sleep(0.02)
    assert called == []

    # A registered synthesizer: fires as that handle.
    engine.handle_summon(_ROOM, "synth-1", _env("human"))
    await asyncio.sleep(0.02)
    assert called == ["synth-1"]


@pytest.mark.asyncio
async def test_summon_lifts_the_full_pass_flag_out_of_the_directive(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.config import settings

    monkeypatch.setattr(settings, "ENGINE_RUNTIME", "backend")
    _register_synthesizer(_ROOM, "synth-1")
    engine = _engine()
    seen: list[tuple[str, bool]] = []

    async def fake_synthesize(
        room: str, engine_handle: str | None = None, directive: str = "", full: bool = False
    ) -> None:
        seen.append((directive, full))

    engine.synthesize = fake_synthesize  # type: ignore[method-assign]

    engine.handle_summon(_ROOM, "synth-1", _env("human"), message_text="@synth-1 --all recap us")
    await asyncio.sleep(0.02)
    engine.handle_summon(_ROOM, "synth-1", _env("human"), message_text="@synth-1 recap us all")
    await asyncio.sleep(0.02)

    # ``_AT_MENTION`` strips the sigil, not the handle — the flag is what is lifted.
    assert seen == [("synth-1 recap us", True), ("synth-1 recap us all", False)]


@pytest.mark.asyncio
async def test_summon_skipped_when_engine_runtime_host(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.config import settings

    _register_synthesizer(_ROOM, "synth-1")
    monkeypatch.setattr(settings, "ENGINE_RUNTIME", "host")
    engine = _engine()
    called: list[str] = []

    async def fake_synthesize(
        room: str, engine_handle: str | None = None, directive: str = "", full: bool = False
    ) -> None:
        called.append(engine_handle or "?")

    engine.synthesize = fake_synthesize  # type: ignore[method-assign]

    engine.handle_summon(_ROOM, "synth-1", _env("human"))
    await asyncio.sleep(0.02)
    assert called == []  # the host daemon owns the run


# ── the shared type table ──────────────────────────────────────────────────────


def test_prose_messages_reads_the_room_by_type() -> None:
    _knowledge(_ROOM, "k-1", at=_T0)
    _chat(_ROOM, "m-1", sender="agent-a", text="said out loud", at=_T0 + timedelta(minutes=1))

    chat = persister.prose_messages(_ROOM)

    assert [m.content for m in chat] == ["said out loud"]
    # The frame is in the room's feed — it is the *type* that excludes it here.
    feed = persister.room_conversation(_ROOM)
    assert any(m.message_type == "l9_knowledge" for m in feed)
    assert all(json.loads(m.content) for m in feed if m.message_type == "l9_knowledge")
