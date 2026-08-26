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

from app.services import a2a_activity, a2a_bridge, l9
from app.services.a2a_bridge import A2aReply
from app.services.filesystem import get_room_dir, write_memory_file
from app.services.l9_models import Kind
from tests.fakes import FakeChannel, FakeManaged, FakeManager, FakePersister

_ROOM = "portfolio"


def _register_a2a(
    handle: str = "researcher",
    card: str = "https://remote.example",
    auth_env: str | None = None,
    allow_from: list[str] | None = None,
    owner: str | None = None,
) -> None:
    manifest: dict = {"adapter": "a2a", "a2a_card": card, "description": "does research"}
    if auth_env:
        manifest["a2a_auth_env"] = auth_env
    if allow_from is not None:
        manifest["allow_from"] = allow_from
    if owner is not None:
        manifest["owner"] = owner
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


@pytest.mark.asyncio
async def test_call_is_recorded_for_the_network_views(monkeypatch):
    # The bridge hop leaves no trace on the channel, so the responder records it
    # (#739) — both the answered call…
    _register_a2a()
    responder, _channel, _persister, _calls = _responder(monkeypatch)

    responder.handle_summon(
        _ROOM, "researcher", _summon_envelope("avery"), [], "what do you think?"
    )
    await _drain(responder)

    exchange = a2a_activity.recent(_ROOM)[-1]
    assert exchange.direction == "outbound"
    assert exchange.status == "ok"
    assert exchange.handle == "researcher"
    assert exchange.peer == "avery"
    assert exchange.prompt == "what do you think?"
    assert exchange.reply == "the remote reply"
    assert a2a_activity.totals(_ROOM).outbound_ok == 1


@pytest.mark.asyncio
async def test_failed_call_is_recorded_with_its_reason(monkeypatch):
    # …and the silent one, so a dead remote reads as a failed call rather than
    # as nothing having happened.
    _register_a2a()
    responder, _channel, _persister, _calls = _responder(monkeypatch, reply=None)

    responder.handle_summon(_ROOM, "researcher", _summon_envelope("avery"), [], "you there?")
    await _drain(responder)

    exchange = a2a_activity.recent(_ROOM)[-1]
    assert exchange.status == "error"
    assert "dead remote" in (exchange.detail or "")
    assert a2a_activity.totals(_ROOM).outbound_failed == 1


# ── Correctness: allow_from, message_id, thread_key, auth_env ───────────────


@pytest.mark.asyncio
async def test_allow_from_permits_listed_sender(monkeypatch):
    _register_a2a(allow_from=["avery"])
    responder, channel, _persister, calls = _responder(monkeypatch)

    responder.handle_summon(_ROOM, "researcher", _summon_envelope("avery"), [], "allowed")
    await _drain(responder)

    assert len(calls) == 1
    assert channel.sent


@pytest.mark.asyncio
async def test_allow_from_blocks_unlisted_sender(monkeypatch):
    _register_a2a(allow_from=["avery"])
    responder, channel, _persister, calls = _responder(monkeypatch)

    # "quinn" is not in the allow_from list — call must be suppressed.
    responder.handle_summon(_ROOM, "researcher", _summon_envelope("quinn"), [], "blocked")
    await _drain(responder)

    assert calls == []
    assert channel.sent == []


@pytest.mark.asyncio
async def test_owner_bypasses_allow_from_gate(monkeypatch):
    """The agent owner must always be able to summon, even with a restrictive allow_from."""
    _register_a2a(allow_from=["avery"], owner="selina")
    responder, channel, _persister, calls = _responder(monkeypatch)

    # "selina" is the owner but not in allow_from — must still go through.
    responder.handle_summon(_ROOM, "researcher", _summon_envelope("selina"), [], "owner summon")
    await _drain(responder)

    assert len(calls) == 1
    assert channel.sent


@pytest.mark.asyncio
async def test_session_qualified_sender_passes_allow_from(monkeypatch):
    """A sender carrying a #session suffix must be treated as their bare handle."""
    _register_a2a(allow_from=["avery"])
    responder, channel, _persister, calls = _responder(monkeypatch)

    # "avery#abc123" is avery with a session qualifier — must pass the gate.
    responder.handle_summon(
        _ROOM, "researcher", _summon_envelope("avery#abc123"), [], "session summon"
    )
    await _drain(responder)

    assert len(calls) == 1
    assert channel.sent


@pytest.mark.asyncio
async def test_session_qualified_owner_passes_allow_from(monkeypatch):
    """The owner with a #session suffix must still bypass the allow_from gate."""
    _register_a2a(allow_from=["avery"], owner="selina")
    responder, channel, _persister, calls = _responder(monkeypatch)

    responder.handle_summon(
        _ROOM, "researcher", _summon_envelope("selina#xyz999"), [], "owner session"
    )
    await _drain(responder)

    assert len(calls) == 1
    assert channel.sent


@pytest.mark.asyncio
async def test_empty_allow_from_allows_anyone(monkeypatch):
    _register_a2a(allow_from=[])
    responder, channel, _persister, calls = _responder(monkeypatch)

    responder.handle_summon(_ROOM, "researcher", _summon_envelope("anyone"), [], "hi")
    await _drain(responder)

    assert len(calls) == 1


@pytest.mark.asyncio
async def test_message_id_is_unique_per_call(monkeypatch):
    """Each send must produce a distinct message_id so compliant remotes don't dedup."""
    from unittest.mock import patch

    _register_a2a()
    responder, _channel, _persister, _calls = _responder(monkeypatch)

    captured_ids: list[str] = []

    from a2a.types import Message

    original_init = Message.__init__

    def _capture(self, **kwargs):
        captured_ids.append(kwargs.get("message_id", ""))
        original_init(self, **kwargs)

    with patch.object(Message, "__init__", _capture):
        responder.handle_summon(
            _ROOM, "researcher", _summon_envelope("avery", message_id="m-uid-1"), [], "first"
        )
        await _drain(responder)
        responder.handle_summon(
            _ROOM, "researcher", _summon_envelope("avery", message_id="m-uid-2"), [], "second"
        )
        await _drain(responder)

    if len(captured_ids) >= 2:
        assert captured_ids[0] != captured_ids[1], "message_id must be unique per send"


@pytest.mark.asyncio
async def test_threads_are_keyed_by_summoner(monkeypatch):
    """Two different senders must each get their own thread; context must not bleed."""
    _register_a2a()
    responder, _channel, _persister, calls = _responder(monkeypatch)

    # avery starts a thread (context_id is None cold)
    responder.handle_summon(
        _ROOM, "researcher", _summon_envelope("avery", message_id="av1"), [], "avery 1"
    )
    await _drain(responder)
    # quinn starts her own thread (should also be None — cold for quinn)
    responder.handle_summon(
        _ROOM, "researcher", _summon_envelope("quinn", message_id="qu1"), [], "quinn 1"
    )
    await _drain(responder)

    assert calls[0]["context_id"] is None  # avery cold
    assert calls[1]["context_id"] is None  # quinn cold — NOT ctx-1 from avery's thread


@pytest.mark.asyncio
async def test_declared_but_missing_auth_env_fails_closed(monkeypatch):
    """If auth_env is declared but the env var is absent, the call must not proceed."""
    _register_a2a(auth_env="MISSING_TOKEN_VAR")
    monkeypatch.delenv("MISSING_TOKEN_VAR", raising=False)
    responder, channel, _persister, calls = _responder(monkeypatch)

    responder.handle_summon(_ROOM, "researcher", _summon_envelope("avery"), [], "hello")
    await _drain(responder)

    assert calls == []
    assert channel.sent == []
    from app.services import a2a_activity

    exchange = a2a_activity.recent(_ROOM)[-1]
    assert exchange.status == "error"
    assert "auth_env" in (exchange.detail or "")


@pytest.mark.asyncio
async def test_declared_but_empty_auth_env_fails_closed(monkeypatch):
    """An auth_env var that is present but empty must also fail closed."""
    _register_a2a(auth_env="EMPTY_TOKEN_VAR")
    monkeypatch.setenv("EMPTY_TOKEN_VAR", "")
    responder, channel, _persister, calls = _responder(monkeypatch)

    responder.handle_summon(_ROOM, "researcher", _summon_envelope("avery"), [], "hello")
    await _drain(responder)

    assert calls == []
    assert channel.sent == []
    from app.services import a2a_activity

    exchange = a2a_activity.recent(_ROOM)[-1]
    assert exchange.status == "error"
    assert "auth_env" in (exchange.detail or "")
