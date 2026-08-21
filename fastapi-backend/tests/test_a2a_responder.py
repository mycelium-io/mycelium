# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""The A2A responder (#714) — answer @-mentions by calling the remote agent.

Node-free: the remote call (`send_to_a2a`) is patched, so these exercise the
summon gate, the loop guards, and that the reply is posted back as the handle.
"""

from __future__ import annotations

import asyncio

import pytest
import yaml

from app.services import a2a_bridge, l9
from app.services.a2a_bridge import A2aReply
from app.services.filesystem import get_room_dir, write_memory_file
from app.services.l9_models import Kind
from tests.fakes import FakeChannel, FakeManaged, FakeManager, FakePersister

_ROOM = "portfolio"


def _register_a2a(
    handle: str = "researcher",
    card: str = "https://remote.example",
    auth_env: str | None = None,
) -> None:
    manifest = {"adapter": "a2a", "a2a_card": card, "description": "does research"}
    if auth_env:
        manifest["a2a_auth_env"] = auth_env
    write_memory_file(
        get_room_dir(_ROOM), f"agents/{handle}", yaml.safe_dump(manifest), created_by="web-ui"
    )


def _register_engine(handle: str = "aligner") -> None:
    body = yaml.safe_dump({"adapter": "engine", "kind": "aligner"})
    write_memory_file(get_room_dir(_ROOM), f"agents/{handle}", body, created_by="web-ui")


def _summon_envelope(sender: str, *, message_id: str = "m1"):
    return l9.build_envelope(
        kind=Kind.exchange,
        episode=l9.episode_urn(_ROOM, "live"),
        sender=sender,
        sender_role="human",
        recipients=["researcher"],
        topic=l9.topic_urn(_ROOM),
        payload_type="message",
        message_id=message_id,
    )


def _responder(monkeypatch, *, reply: str | None = "the remote reply"):
    persister = FakePersister()
    channel = FakeChannel(persister)
    managed = FakeManaged(room=_ROOM, channel=channel, persister=persister)
    manager = FakeManager(managed, ["avery", "researcher"])
    responder = a2a_bridge.A2aResponder(manager)  # type: ignore[arg-type]

    calls: list[dict] = []

    async def _fake_send(card_url, text, *, context_id=None, auth_token=None, **_kwargs):
        calls.append(
            {"card": card_url, "text": text, "context_id": context_id, "auth_token": auth_token}
        )
        if reply is None:
            raise a2a_bridge.A2aSendError("dead remote")
        return A2aReply(text=reply, context_id="ctx-1")

    monkeypatch.setattr(a2a_bridge, "send_to_a2a", _fake_send)
    return responder, channel, persister, calls


async def _drain(responder):
    if responder._tasks:
        await asyncio.gather(*list(responder._tasks))


@pytest.mark.asyncio
async def test_mention_calls_remote_and_posts_reply(monkeypatch):
    _register_a2a()
    responder, channel, persister, calls = _responder(monkeypatch)

    responder.handle_summon(
        _ROOM, "researcher", _summon_envelope("avery"), [], "what do you think?"
    )
    await _drain(responder)

    # It called the remote with the attributed message text…
    assert len(calls) == 1
    assert calls[0]["card"] == "https://remote.example"
    assert calls[0]["text"] == "@avery: what do you think?"
    # …and posted the reply back into the room as the handle.
    assert len(channel.sent) == 1
    env, extra = channel.sent[0]
    assert extra["content"] == "the remote reply"
    assert env.header.participants.actors[0].id == "researcher"
    assert persister.ingested


@pytest.mark.asyncio
async def test_thread_continues_across_mentions(monkeypatch):
    _register_a2a()
    responder, _channel, _persister, calls = _responder(monkeypatch)

    # First mention starts a thread; the second continues the same context id.
    responder.handle_summon(
        _ROOM, "researcher", _summon_envelope("avery", message_id="m1"), [], "one"
    )
    await _drain(responder)
    responder.handle_summon(
        _ROOM, "researcher", _summon_envelope("avery", message_id="m2"), [], "two"
    )
    await _drain(responder)

    assert calls[0]["context_id"] is None  # cold start
    assert calls[1]["context_id"] == "ctx-1"  # threaded from the first reply


@pytest.mark.asyncio
async def test_auth_token_resolved_from_env_not_manifest(monkeypatch):
    monkeypatch.setenv("RESEARCHER_TOKEN", "s3cret")
    _register_a2a(auth_env="RESEARCHER_TOKEN")
    responder, _channel, _persister, calls = _responder(monkeypatch)

    responder.handle_summon(_ROOM, "researcher", _summon_envelope("avery"), [], "hi")
    await _drain(responder)

    assert calls[0]["auth_token"] == "s3cret"


@pytest.mark.asyncio
async def test_no_auth_env_means_no_token(monkeypatch):
    _register_a2a()  # no a2a_auth_env
    responder, _channel, _persister, calls = _responder(monkeypatch)

    responder.handle_summon(_ROOM, "researcher", _summon_envelope("avery"), [], "hi")
    await _drain(responder)

    assert calls[0]["auth_token"] is None


@pytest.mark.asyncio
async def test_non_a2a_handle_is_ignored(monkeypatch):
    _register_engine("aligner")  # an engine, not a2a
    responder, channel, _persister, calls = _responder(monkeypatch)

    responder.handle_summon(_ROOM, "aligner", _summon_envelope("avery"), [], "mediate us")
    await _drain(responder)

    assert calls == []
    assert channel.sent == []


@pytest.mark.asyncio
async def test_a2a_agent_does_not_summon_another_a2a(monkeypatch):
    # Runaway guard: @alpha (a registered a2a agent) posting a message that
    # mentions @beta must NOT trigger beta's remote call — else two agents that
    # mention each other ping-pong forever.
    _register_a2a("beta", card="https://beta.example")
    _register_a2a("alpha", card="https://alpha.example")
    responder, channel, _persister, calls = _responder(monkeypatch)

    responder.handle_summon(_ROOM, "beta", _summon_envelope("alpha"), [], "hey @beta")
    await _drain(responder)

    assert calls == []
    assert channel.sent == []


@pytest.mark.asyncio
async def test_self_message_does_not_loop(monkeypatch):
    _register_a2a()
    responder, channel, _persister, calls = _responder(monkeypatch)

    # The summoner IS the a2a agent — its own post must not trigger a reply.
    responder.handle_summon(_ROOM, "researcher", _summon_envelope("researcher"), [], "hi all")
    await _drain(responder)

    assert calls == []
    assert channel.sent == []


@pytest.mark.asyncio
async def test_empty_prompt_is_ignored(monkeypatch):
    _register_a2a()
    responder, _channel, _persister, calls = _responder(monkeypatch)

    responder.handle_summon(_ROOM, "researcher", _summon_envelope("avery"), [], "   ")
    await _drain(responder)
    assert calls == []


@pytest.mark.asyncio
async def test_same_mention_runs_once(monkeypatch):
    _register_a2a()
    responder, _channel, _persister, calls = _responder(monkeypatch)

    env = _summon_envelope("avery", message_id="dup")
    responder.handle_summon(_ROOM, "researcher", env, [], "hello")
    responder.handle_summon(_ROOM, "researcher", env, [], "hello")
    await _drain(responder)
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_dead_remote_posts_nothing(monkeypatch):
    _register_a2a()
    responder, channel, _persister, calls = _responder(monkeypatch, reply=None)

    responder.handle_summon(_ROOM, "researcher", _summon_envelope("avery"), [], "you there?")
    await _drain(responder)

    assert calls  # it tried
    assert channel.sent == []  # fail-faithful: no fabricated reply
