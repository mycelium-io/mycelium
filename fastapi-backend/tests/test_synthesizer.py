# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""Unit tests for the synthesizer cognition engine (app/services/synthesizer.py).

Node-free: the Pi turn is patched, so these exercise the summon gate, the
read → summarize → write path, the fail-soft behavior, and the exclusion of
manifests / the prior summary from the corpus — all as pure async logic against
a temp ``.mycelium`` dir.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest
import yaml

from app.services import l9, synthesizer
from app.services.filesystem import get_room_dir, read_memory_file, write_memory_file
from app.services.l9_models import Kind
from tests.fakes import FakeChannel, FakeManaged, FakeManager, FakePersister

_ROOM = "synth-room"
_EPISODE = l9.episode_urn(_ROOM, "live")
_TOPIC = l9.topic_urn(_ROOM)


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


@pytest.fixture(autouse=True)
def _fast_embed(monkeypatch: pytest.MonkeyPatch) -> None:
    """Skip the ONNX embedding model — the write path is what we're testing."""
    monkeypatch.setattr("app.routes.memory.embed_text", lambda _text: [0.0])


# ── the read → summarize → write path ──────────────────────────────────────────


@pytest.mark.asyncio
async def test_synthesize_writes_summary(monkeypatch: pytest.MonkeyPatch) -> None:
    _seed_memories(_ROOM)
    seen_prompt: list[str] = []

    def fake_pi(prompt: str, _timeout: float) -> str:
        seen_prompt.append(prompt)
        return "# Room briefing\n\n- DB: PostgreSQL\n- Status: scaffolding"

    monkeypatch.setattr(synthesizer, "_pi_complete", fake_pi)

    result = await _engine().synthesize(_ROOM)

    assert result is not None
    assert "Room briefing" in result
    written = read_memory_file(get_room_dir(_ROOM), synthesizer.SYNTHESIS_KEY)
    assert written is not None
    _meta, body = written
    assert "Room briefing" in body
    # The corpus fed to Pi carried the source memories.
    assert "PostgreSQL" in seen_prompt[0]
    assert "scaffolding" in seen_prompt[0]


@pytest.mark.asyncio
async def test_synthesize_excludes_manifests_and_prior_summary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _seed_memories(_ROOM)
    # A manifest and a prior synthesis must never feed the next summary.
    write_memory_file(
        get_room_dir(_ROOM),
        "agents/synth-1",
        yaml.safe_dump({"adapter": "engine", "kind": "synthesizer"}),
        created_by="cli-user",
    )
    write_memory_file(
        get_room_dir(_ROOM),
        synthesizer.SYNTHESIS_KEY,
        "STALE PRIOR SUMMARY",
        created_by="synthesizer",
    )
    seen_prompt: list[str] = []
    monkeypatch.setattr(synthesizer, "_pi_complete", lambda p, _t: seen_prompt.append(p) or "ok")

    await _engine().synthesize(_ROOM)

    assert "adapter: engine" not in seen_prompt[0]
    assert "STALE PRIOR SUMMARY" not in seen_prompt[0]


@pytest.mark.asyncio
async def test_synthesize_noop_on_empty_room(monkeypatch: pytest.MonkeyPatch) -> None:
    get_room_dir(_ROOM).mkdir(parents=True, exist_ok=True)  # exists but no memory

    def boom(_p: str, _t: float) -> str:
        raise AssertionError("Pi must not run for an empty room")

    monkeypatch.setattr(synthesizer, "_pi_complete", boom)

    assert await _engine().synthesize(_ROOM) is None
    assert read_memory_file(get_room_dir(_ROOM), synthesizer.SYNTHESIS_KEY) is None


@pytest.mark.asyncio
async def test_synthesize_failsoft_on_pi_error(monkeypatch: pytest.MonkeyPatch) -> None:
    _seed_memories(_ROOM)

    def boom(_p: str, _t: float) -> str:
        raise RuntimeError("pi exploded")

    monkeypatch.setattr(synthesizer, "_pi_complete", boom)

    # No exception escapes, no partial summary is written.
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
    write_memory_file(
        get_room_dir(_ROOM),
        "agents/synth-1",
        yaml.safe_dump({"adapter": "engine", "kind": "synthesizer"}),
        created_by="cli-user",
    )
    write_memory_file(
        get_room_dir(_ROOM),
        "agents/mediator-1",
        yaml.safe_dump({"adapter": "engine", "kind": "aligner"}),
        created_by="cli-user",
    )
    engine = _engine()
    called: list[str] = []

    async def fake_synthesize(room: str, engine_handle: str | None = None, directive: str = "") -> None:
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
async def test_summon_skipped_when_engine_runtime_host(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.config import settings

    write_memory_file(
        get_room_dir(_ROOM),
        "agents/synth-1",
        yaml.safe_dump({"adapter": "engine", "kind": "synthesizer"}),
        created_by="cli-user",
    )
    monkeypatch.setattr(settings, "ENGINE_RUNTIME", "host")
    engine = _engine()
    called: list[str] = []

    async def fake_synthesize(room: str, engine_handle: str | None = None, directive: str = "") -> None:
        called.append(engine_handle or "?")

    engine.synthesize = fake_synthesize  # type: ignore[method-assign]

    engine.handle_summon(_ROOM, "synth-1", _env("human"))
    await asyncio.sleep(0.02)
    assert called == []  # the host daemon owns the run
