# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""The persona engine: a member played by a model, in character, that remembers.

Node-free; the Pi turn is patched. What these hold: the character comes from
the notes memory (then the description, then a default); the answer lands
where the ask was made with any stance lifted onto the payload and every
sigil neutralized; both seams gate on the manifest kind; and a persona is
fail-loud rather than silent.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest
import yaml

from app.services import l9, persona_engine
from app.services.filesystem import get_room_dir, write_memory_file
from app.services.l9_models import Kind
from tests.fakes import FakeChannel, FakeManaged, FakeManager, FakePersister

_ROOM = "persona-room"
_LIVE = l9.live_episode_urn(_ROOM)
_THREAD = l9.episode_urn(_ROOM, "t1")


def _engine() -> tuple[persona_engine.PersonaEngine, FakeManaged]:
    managed = FakeManaged(_ROOM, "mycelium", FakeChannel(), FakePersister())
    return persona_engine.PersonaEngine(FakeManager(managed, [])), managed  # type: ignore[arg-type]


def _register(handle: str, kind: str, description: str = "") -> None:
    write_memory_file(
        get_room_dir(_ROOM),
        f"agents/{handle}",
        yaml.safe_dump({"adapter": "engine", "kind": kind, "description": description}),
        created_by="julia",
    )


def _notes(handle: str, text: str) -> None:
    write_memory_file(get_room_dir(_ROOM), f"agents/{handle}/notes", text, created_by="julia")


def _env(sender: str, *, episode: str = _LIVE, recipients: list[str] | None = None) -> Any:
    return l9.build_envelope(
        kind=Kind.exchange,
        episode=episode,
        sender=sender,
        recipients=recipients,
        topic=l9.topic_urn(_ROOM),
        payload_type="tick" if recipients else "message",
    )


def _posted(managed: FakeManaged) -> list[tuple[Any, str]]:
    return [(env, (extra or {}).get("content", "")) for env, extra in managed.channel.sent]


@pytest.fixture(autouse=True)
def _backend_runtime(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.config import settings

    monkeypatch.setattr(settings, "ENGINE_RUNTIME", "backend")
    get_room_dir(_ROOM)


def _patch_pi(monkeypatch: pytest.MonkeyPatch, reply: str) -> list[dict[str, str]]:
    seen: list[dict[str, str]] = []

    def fake(room: str, handle: str, prompt: str, system: str, _t: float) -> str:
        seen.append({"room": room, "handle": handle, "prompt": prompt, "system": system})
        return reply

    monkeypatch.setattr(persona_engine, "_pi_complete", fake)
    return seen


# ── the character ──────────────────────────────────────────────────────────────


def test_the_notes_memory_is_the_character():
    _register("sec", "persona", description="a reviewer")
    _notes("sec", "You are the security reviewer. You block anything without a rollback plan.")
    assert persona_engine._persona_text(_ROOM, "sec").startswith("You are the security reviewer")


def test_without_notes_the_description_is_and_then_a_default():
    _register("brazil", "persona", description="A coffee farm with 40 bags in stock.")
    assert persona_engine._persona_text(_ROOM, "brazil") == "A coffee farm with 40 bags in stock."
    _register("blank", "persona")
    assert persona_engine._persona_text(_ROOM, "blank") == persona_engine.DEFAULT_PERSONA


def test_the_session_is_per_room_and_handle():
    a = persona_engine._session_path(_ROOM, "sec")
    assert a == persona_engine._session_path(_ROOM, "sec")
    assert a != persona_engine._session_path(_ROOM, "api")
    assert a != persona_engine._session_path("other-room", "sec")
    assert a.suffix == ".jsonl"


# ── answering ──────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_it_answers_in_character_where_it_was_asked(monkeypatch: pytest.MonkeyPatch):
    _register("sec", "persona")
    _notes("sec", "You are the security reviewer.")
    seen = _patch_pi(monkeypatch, "No rollback plan, so no. [[mycelium: stance=reject]]")
    engine, managed = _engine()

    reply = await engine.answer(
        _ROOM,
        engine_handle="sec",
        episode=_THREAD,
        sender="conductor",
        text="Approve or block: rotate the key in place",
    )

    assert reply == "No rollback plan, so no."
    assert seen[0]["system"] == "You are the security reviewer."
    assert "rotate the key in place" in seen[0]["prompt"]
    assert "in a task's thread" in seen[0]["prompt"]
    env, text = _posted(managed)[0]
    assert text == "No rollback plan, so no."
    assert env.header.message.episode == _THREAD
    assert env.header.participants.actors[0].id == "sec"
    # The stance rides the payload, the way the reply route lifts it, so the
    # conductor and the aligner read it off the same place.
    assert env.payload.data == {"action": "reject"}


@pytest.mark.asyncio
async def test_it_never_puts_a_sigil_in_front_of_a_name(monkeypatch: pytest.MonkeyPatch):
    _register("sec", "persona")
    _patch_pi(monkeypatch, "Ask @api to add a canary first, @julia.")
    engine, managed = _engine()

    reply = await engine.answer(_ROOM, engine_handle="sec", sender="julia", text="thoughts?")

    assert reply == "Ask api to add a canary first, julia."
    assert "@" not in _posted(managed)[0][1]


@pytest.mark.asyncio
async def test_a_plain_answer_carries_no_stance(monkeypatch: pytest.MonkeyPatch):
    _register("sec", "persona")
    _patch_pi(monkeypatch, "```\nStill thinking it over.\n```")
    engine, managed = _engine()

    await engine.answer(_ROOM, engine_handle="sec", sender="julia", text="thoughts?")

    env, text = _posted(managed)[0]
    assert text == "Still thinking it over."
    assert env.payload.data == {"action": "reply"}
    assert env.header.message.episode == _LIVE


@pytest.mark.asyncio
async def test_pi_error_and_empty_answer_are_said_plainly(monkeypatch: pytest.MonkeyPatch):
    _register("sec", "persona")
    engine, managed = _engine()

    def boom(*_a: Any) -> str:
        raise RuntimeError("pi exploded")

    monkeypatch.setattr(persona_engine, "_pi_complete", boom)
    assert await engine.answer(_ROOM, engine_handle="sec", text="hi") is None
    assert "timed out or errored" in _posted(managed)[0][1]

    monkeypatch.setattr(persona_engine, "_pi_complete", lambda *_a: "  \n")
    assert await engine.answer(_ROOM, engine_handle="sec", text="hi") is None
    assert "empty response" in _posted(managed)[1][1]


# ── the two seams ──────────────────────────────────────────────────────────────


def _capture(engine: persona_engine.PersonaEngine) -> list[dict[str, Any]]:
    calls: list[dict[str, Any]] = []

    async def fake_answer(room: str, **kw: Any) -> str:
        calls.append({"room": room, **kw})
        return "ok"

    engine.answer = fake_answer  # type: ignore[method-assign]
    return calls


@pytest.mark.asyncio
async def test_a_mention_fires_only_a_registered_persona():
    _register("sec", "persona")
    _register("hi", "hello")
    _register("api", "conductor")
    engine, _managed = _engine()
    calls = _capture(engine)

    engine.handle_summon(
        _ROOM, "sec", _env("julia"), ["sec"], "@sec what do you think of @api's plan?"
    )
    engine.handle_summon(_ROOM, "hi", _env("julia"), ["hi"], "@hi hello")
    engine.handle_summon(_ROOM, "api", _env("julia"), ["api"], "@api go")
    engine.handle_summon(_ROOM, "nobody", _env("julia"), ["nobody"], "@nobody go")
    await asyncio.sleep(0.02)

    assert [c["engine_handle"] for c in calls] == ["sec"]
    assert calls[0]["sender"] == "julia"
    assert calls[0]["text"] == "sec what do you think of api's plan?"
    assert calls[0]["episode"] == _LIVE


@pytest.mark.asyncio
async def test_an_addressed_turn_reaches_it_in_its_thread():
    """The conductor's tick names the persona as recipient and nobody in the
    text; the persona answers it in the thread the tick rode."""
    _register("sec", "persona")
    engine, _managed = _engine()
    calls = _capture(engine)

    engine.handle_addressed(
        _ROOM,
        "sec",
        _env("conductor", episode=_THREAD, recipients=["sec"]),
        "Approve or block this",
    )
    engine.handle_addressed(
        _ROOM, "api", _env("conductor", episode=_THREAD, recipients=["api"]), "go"
    )
    await asyncio.sleep(0.02)

    assert len(calls) == 1
    assert calls[0]["episode"] == _THREAD
    assert calls[0]["sender"] == "conductor"


@pytest.mark.asyncio
async def test_it_never_answers_itself_and_drops_a_second_ask_while_busy():
    _register("sec", "persona")
    _register("api", "persona")
    engine, _managed = _engine()
    started: list[str] = []
    release = asyncio.Event()

    async def slow(room: str, **kw: Any) -> str:
        started.append(kw["engine_handle"])
        await release.wait()
        return "ok"

    engine.answer = slow  # type: ignore[method-assign]

    engine.handle_summon(_ROOM, "sec", _env("sec"), ["sec"], "@sec talking to myself")
    engine.handle_summon(_ROOM, "sec", _env("julia"), ["sec"], "@sec one")
    engine.handle_summon(_ROOM, "sec", _env("julia"), ["sec"], "@sec two")
    engine.handle_addressed(_ROOM, "api", _env("conductor", recipients=["api"]), "go")
    await asyncio.sleep(0.02)
    release.set()

    assert started == ["sec", "api"]


@pytest.mark.asyncio
async def test_host_runtime_leaves_it_to_the_host(monkeypatch: pytest.MonkeyPatch):
    from app.config import settings

    _register("sec", "persona")
    monkeypatch.setattr(settings, "ENGINE_RUNTIME", "host")
    engine, _managed = _engine()
    calls = _capture(engine)

    engine.handle_summon(_ROOM, "sec", _env("julia"), ["sec"], "@sec hi")
    await asyncio.sleep(0.02)

    assert calls == []


# ── a role is not a question, and nobody speaks off the floor ──────────────────


@pytest.mark.asyncio
async def test_a_mention_beside_a_conductor_binds_a_role_and_asks_nothing():
    """`@conductor gated @api @sec: …` names the personas that fill the roles.
    The conductor will address each in turn; answering the summon would talk
    over the floor it just took and leave the persona busy for its real turn."""
    _register("sec", "persona")
    _register("maestro", "conductor")
    engine, _managed = _engine()
    calls = _capture(engine)

    summons = ["maestro", "api", "sec"]
    engine.handle_summon(
        _ROOM, "sec", _env("julia", episode=_THREAD), summons, "@maestro gated @api @sec: go"
    )
    await asyncio.sleep(0.02)
    assert calls == []

    # The same persona, mentioned on its own, still answers.
    engine.handle_summon(_ROOM, "sec", _env("julia"), ["sec"], "@sec thoughts?")
    await asyncio.sleep(0.02)
    assert [c["engine_handle"] for c in calls] == ["sec"]


@pytest.mark.asyncio
async def test_it_does_not_post_into_a_thread_whose_floor_it_was_not_given(
    monkeypatch: pytest.MonkeyPatch,
):
    _register("sec", "persona")
    _patch_pi(monkeypatch, "Blocked. [[mycelium: stance=reject]]")
    engine, managed = _engine()
    engine._manager.hold_floor(_ROOM, _THREAD, holder="conductor", speakers=["api"])

    reply = await engine.answer(
        _ROOM, engine_handle="sec", episode=_THREAD, sender="julia", text="go"
    )

    assert reply == "Blocked."
    assert _posted(managed) == [], "the reply was dropped, not posted out of turn"


@pytest.mark.asyncio
async def test_it_posts_when_the_floor_is_its_own(monkeypatch: pytest.MonkeyPatch):
    _register("sec", "persona")
    _patch_pi(monkeypatch, "Blocked. [[mycelium: stance=reject]]")
    engine, managed = _engine()
    engine._manager.hold_floor(_ROOM, _THREAD, holder="conductor", speakers=["sec"])

    await engine.answer(_ROOM, engine_handle="sec", episode=_THREAD, sender="conductor", text="go")

    assert [t for _e, t in _posted(managed)] == ["Blocked."]
