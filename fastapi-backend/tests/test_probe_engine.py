# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""Unit tests for the probe cognition engine (app/services/probe_engine.py).

Node-free: the Pi turn is patched, so these exercise the summon gate, the
one-turn answer path, the fail-loud behavior, and the property that makes the probe
safe to fire into a live room — it writes no memory at all.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest
import yaml

from app.services import l9, probe_engine
from app.services.filesystem import get_room_dir, list_memory_files, write_memory_file
from app.services.l9_models import Kind
from tests.fakes import FakeChannel, FakeManaged, FakeManager, FakePersister

_ROOM = "hello-room"
_EPISODE = l9.episode_urn(_ROOM, "live")
_TOPIC = l9.topic_urn(_ROOM)


def _engine() -> tuple[probe_engine.ProbeEngine, FakeManaged]:
    managed = FakeManaged(_ROOM, "mycelium", FakeChannel(), FakePersister())
    return probe_engine.ProbeEngine(FakeManager(managed, [])), managed  # type: ignore[arg-type]


def _env(sender: str) -> Any:
    return l9.build_envelope(
        kind=Kind.exchange,
        episode=_EPISODE,
        sender=sender,
        topic=_TOPIC,
        payload_type="message",
    )


def _register(handle: str, kind: str) -> None:
    write_memory_file(
        get_room_dir(_ROOM),
        f"agents/{handle}",
        yaml.safe_dump({"adapter": "engine", "kind": kind}),
        created_by="cli-user",
    )


def _said(managed: FakeManaged) -> list[str]:
    return [(extra or {}).get("content", "") for _env, extra in managed.channel.sent]


@pytest.fixture(autouse=True)
def _backend_runtime(monkeypatch: pytest.MonkeyPatch) -> None:
    """Pin the backend runtime — a local ``.env`` may default this to ``host``."""
    from app.config import settings

    monkeypatch.setattr(settings, "ENGINE_RUNTIME", "backend")


# ── the one path: summon text → one Pi turn → a message ────────────────────────


@pytest.mark.asyncio
async def test_greet_answers_the_summon_text(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[str] = []

    def fake_pi(prompt: str, _timeout: float) -> str:
        seen.append(prompt)
        return "Hello — running claude-sonnet-4-6. The engine path works."

    monkeypatch.setattr(probe_engine, "_pi_complete", fake_pi)
    engine, managed = _engine()

    reply = await engine.greet(_ROOM, engine_handle="hi", directive="name the model you are")

    assert reply is not None
    assert "engine path works" in reply
    # The summon text reached Pi, and the reply reached the room.
    assert "name the model you are" in seen[0]
    assert reply in _said(managed)


@pytest.mark.asyncio
async def test_bare_summon_falls_back_to_the_default_directive(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: list[str] = []
    monkeypatch.setattr(probe_engine, "_pi_complete", lambda p, _t: seen.append(p) or "hi")
    engine, _managed = _engine()

    await engine.greet(_ROOM, engine_handle="hi", directive="")

    assert probe_engine.DEFAULT_DIRECTIVE in seen[0]


@pytest.mark.asyncio
async def test_greet_writes_no_memory(monkeypatch: pytest.MonkeyPatch) -> None:
    """The safety property: the only trace is the message it posts."""
    get_room_dir(_ROOM).mkdir(parents=True, exist_ok=True)
    _register("hi", "hello")
    before = {key for key, _meta, _content in list_memory_files(get_room_dir(_ROOM))}
    monkeypatch.setattr(probe_engine, "_pi_complete", lambda _p, _t: "hello there")
    engine, _managed = _engine()

    await engine.greet(_ROOM, engine_handle="hi")

    after = {key for key, _meta, _content in list_memory_files(get_room_dir(_ROOM))}
    assert after == before


@pytest.mark.asyncio
async def test_strips_a_code_fence_the_model_added(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(probe_engine, "_pi_complete", lambda _p, _t: "```\nhello there\n```")
    engine, _managed = _engine()

    assert await engine.greet(_ROOM, engine_handle="hi") == "hello there"


# ── fail-loud: a broken probe says why ─────────────────────────────────────────


@pytest.mark.asyncio
async def test_pi_error_posts_a_readable_reason(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(_p: str, _t: float) -> str:
        raise RuntimeError("pi exploded")

    monkeypatch.setattr(probe_engine, "_pi_complete", boom)
    engine, managed = _engine()

    assert await engine.greet(_ROOM, engine_handle="hi") is None
    assert "timed out or errored" in _said(managed)[0]


@pytest.mark.asyncio
async def test_empty_pi_response_posts_a_readable_reason(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(probe_engine, "_pi_complete", lambda _p, _t: "   \n ")
    engine, managed = _engine()

    assert await engine.greet(_ROOM, engine_handle="hi") is None
    assert "empty response" in _said(managed)[0]


@pytest.mark.asyncio
async def test_pi_timeout_posts_a_readable_reason(monkeypatch: pytest.MonkeyPatch) -> None:
    managed = FakeManaged(_ROOM, "mycelium", FakeChannel(), FakePersister())
    engine = probe_engine.ProbeEngine(FakeManager(managed, []), timeout_s=-5.0)  # type: ignore[arg-type]
    monkeypatch.setattr(probe_engine, "_pi_complete", lambda _p, _t: "never gets here")

    assert await engine.greet(_ROOM, engine_handle="hi") is None
    assert "timed out or errored" in _said(managed)[0]


# ── the summon gate ────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_summon_fires_only_for_a_registered_hello_engine() -> None:
    _register("hi", "hello")
    _register("mediator-1", "aligner")
    _register("distiller", "synthesizer")
    engine, _managed = _engine()
    called: list[str] = []

    async def fake_greet(room: str, engine_handle: str | None = None, directive: str = "") -> None:
        called.append(engine_handle or "?")

    engine.greet = fake_greet  # type: ignore[method-assign]

    # A normal teammate, and the other two engine kinds: no fire.
    engine.handle_summon(_ROOM, "agent-a", _env("human"))
    engine.handle_summon(_ROOM, "mediator-1", _env("human"))
    engine.handle_summon(_ROOM, "distiller", _env("human"))
    await asyncio.sleep(0.02)
    assert called == []

    # A registered hello engine: fires as that handle.
    engine.handle_summon(_ROOM, "hi", _env("human"))
    await asyncio.sleep(0.02)
    assert called == ["hi"]


@pytest.mark.asyncio
async def test_summon_never_fires_on_its_own_message() -> None:
    _register("hi", "hello")
    engine, _managed = _engine()
    called: list[str] = []

    async def fake_greet(room: str, engine_handle: str | None = None, directive: str = "") -> None:
        called.append(engine_handle or "?")

    engine.greet = fake_greet  # type: ignore[method-assign]

    engine.handle_summon(_ROOM, "hi", _env("hi"))
    await asyncio.sleep(0.02)
    assert called == []


@pytest.mark.asyncio
async def test_summon_skipped_when_engine_runtime_host(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.config import settings

    _register("hi", "hello")
    monkeypatch.setattr(settings, "ENGINE_RUNTIME", "host")
    engine, _managed = _engine()
    called: list[str] = []

    async def fake_greet(room: str, engine_handle: str | None = None, directive: str = "") -> None:
        called.append(engine_handle or "?")

    engine.greet = fake_greet  # type: ignore[method-assign]

    engine.handle_summon(_ROOM, "hi", _env("human"))
    await asyncio.sleep(0.02)
    assert called == []  # the host daemon owns the run


@pytest.mark.asyncio
async def test_resummon_while_in_flight_is_ignored_per_handle() -> None:
    _register("hi", "hello")
    _register("hi-2", "hello")
    engine, _managed = _engine()
    started: list[str] = []
    release = asyncio.Event()

    async def slow_greet(room: str, engine_handle: str | None = None, directive: str = "") -> None:
        started.append(engine_handle or "?")
        await release.wait()

    engine.greet = slow_greet  # type: ignore[method-assign]

    engine.handle_summon(_ROOM, "hi", _env("human"))
    engine.handle_summon(_ROOM, "hi", _env("human"))  # same engine, still busy
    engine.handle_summon(_ROOM, "hi-2", _env("human"))  # a second engine is unaffected
    await asyncio.sleep(0.02)
    assert started == ["hi", "hi-2"]

    # Once the turn lands, the same handle can be summoned again.
    release.set()
    await asyncio.sleep(0.02)
    engine.handle_summon(_ROOM, "hi", _env("human"))
    await asyncio.sleep(0.02)
    assert started == ["hi", "hi-2", "hi"]


@pytest.mark.asyncio
async def test_summon_strips_the_mention_from_the_directive(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _register("hi", "hello")
    seen: list[str] = []
    monkeypatch.setattr(probe_engine, "_pi_complete", lambda p, _t: seen.append(p) or "ok")
    engine, _managed = _engine()

    engine.handle_summon(_ROOM, "hi", _env("human"), None, "@hi are you there")
    await asyncio.sleep(0.05)

    assert "hi are you there" in seen[0]
