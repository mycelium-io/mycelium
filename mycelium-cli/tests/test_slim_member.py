# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""The member-session core — membership as a runtime-agnostic primitive.

Node-free: these pin the wake decision, reply threading, and the reconnecting
message stream (with a fake SlimClient) that both the daemon and the ``await`` /
``respond`` commands sit on. Keeps the CLI member and the daemon member on one
implementation so they can't drift.
"""

from __future__ import annotations

from typing import Any

import pytest

from mycelium.config import MyceliumConfig, ServerConfig
from mycelium.slim import l9, member
from tests.conftest import FakeSlimClient


def _exchange(sender: str, recipients: list[str], text: str, *, mid: str = "m1") -> dict:
    return l9.build_reply_content(
        sender=sender,
        recipients=recipients,
        episode="urn:ioc:mycelium:episode:r:live",
        parents=[],
        topic="urn:concept:mycelium:r",
        text=text,
        message_id=mid,
        payload_type="tick",
    )


# ── wake decision ─────────────────────────────────────────────────────────────


def test_should_wake_on_recipient() -> None:
    assert member.should_wake(_exchange("backend", ["agent-a"], "take a turn"), "agent-a")


def test_should_wake_on_mention() -> None:
    assert member.should_wake(_exchange("human", [], "hey @agent-a look"), "agent-a")


def test_should_not_wake_on_own_reply() -> None:
    assert not member.should_wake(_exchange("agent-a", ["agent-a"], "self"), "agent-a")


def test_should_not_wake_unaddressed() -> None:
    assert not member.should_wake(_exchange("backend", ["other"], "for someone else"), "agent-a")


def test_should_not_wake_on_non_exchange() -> None:
    knowledge = _exchange("backend", ["agent-a"], "x")
    knowledge["l9"]["header"]["kind"] = l9.KNOWLEDGE_KIND
    assert not member.should_wake(knowledge, "agent-a")


# ── reply threading ───────────────────────────────────────────────────────────


def test_build_reply_parents_on_woke_and_keeps_episode() -> None:
    woke = _exchange("backend", ["agent-a"], "@agent-a go", mid="woke-9")
    reply = member.build_reply(handle="agent-a", room="r", woke=woke, text="done")
    assert l9.kind_of(reply) == l9.EXCHANGE_KIND
    assert l9.sender_of(reply) == "agent-a"
    assert reply["l9"]["header"]["message"]["parents"] == ["woke-9"]
    assert l9.episode_of(reply) == "urn:ioc:mycelium:episode:r:live"
    assert l9.human_text_of(reply) == "done"


def test_build_reply_with_no_woke_falls_back_to_room_episode() -> None:
    reply = member.build_reply(handle="agent-a", room="r", woke={}, text="standalone")
    assert reply["l9"]["header"]["message"]["parents"] == []
    assert l9.episode_of(reply) == member.room_episode("r")


def test_build_reply_lifts_position_marker() -> None:
    woke = _exchange("backend", ["agent-a"], "@agent-a go", mid="w")
    reply = member.build_reply(
        handle="agent-a",
        room="r",
        woke=woke,
        text="I accept. [[mycelium: confidence=0.9 stance=accept]]",
    )
    assert l9.human_text_of(reply) == "I accept."
    data = l9.payload_data_of(reply)
    assert data["confidence"] == 0.9
    assert data["action"] == "accept"


# ── the message stream (fake transport) ───────────────────────────────────────


def _cfg() -> MyceliumConfig:
    return MyceliumConfig(server=ServerConfig(api_url="http://localhost:8000"))


@pytest.mark.asyncio
async def test_await_addressed_returns_first_addressed(monkeypatch: pytest.MonkeyPatch) -> None:
    # No node: stub SlimClient and the presence announce (best-effort HTTP).
    monkeypatch.setattr(member, "SlimClient", FakeSlimClient)
    monkeypatch.setattr(member, "announce_presence", _noop_announce)
    monkeypatch.setattr(member, "KEEPALIVE_INTERVAL_S", 3600)  # keep it out of the way
    FakeSlimClient.published = []
    FakeSlimClient.inbox = [
        l9.serialize(_keepalive("other")),  # dropped
        l9.serialize(_exchange("backend", ["other"], "not me")),  # not addressed
        l9.serialize(_exchange("backend", ["agent-a"], "@agent-a your turn", mid="hit")),
    ]

    content = await member.await_addressed(_cfg(), "r", "agent-a", timeout_s=2)
    assert content is not None
    assert l9.message_id_of(content) == "hit"


@pytest.mark.asyncio
async def test_stream_applies_knowledge_and_swallows_it(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(member, "SlimClient", FakeSlimClient)
    monkeypatch.setattr(member, "announce_presence", _noop_announce)
    monkeypatch.setattr(member, "KEEPALIVE_INTERVAL_S", 3600)
    applied: list[dict] = []
    reindexed: list[str] = []
    monkeypatch.setattr(
        member,
        "apply_knowledge_message",
        lambda room, content: applied.append(content) or _Applied(),
    )

    async def _reindex(_config: Any, room: str) -> None:
        reindexed.append(room)

    monkeypatch.setattr(member, "reindex_after_knowledge", _reindex)

    knowledge = _exchange("backend", [], "plan updated")
    knowledge["l9"]["header"]["kind"] = l9.KNOWLEDGE_KIND
    FakeSlimClient.published = []
    FakeSlimClient.inbox = [
        l9.serialize(knowledge),
        l9.serialize(_exchange("backend", ["agent-a"], "@agent-a go", mid="hit")),
    ]

    content = await member.await_addressed(_cfg(), "r", "agent-a", timeout_s=2)
    # Knowledge was applied + reindexed and never surfaced as an addressed turn.
    assert applied and reindexed == ["r"]
    assert content is not None and l9.message_id_of(content) == "hit"


@pytest.mark.asyncio
async def test_await_addressed_times_out(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(member, "SlimClient", FakeSlimClient)
    monkeypatch.setattr(member, "announce_presence", _noop_announce)
    monkeypatch.setattr(member, "KEEPALIVE_INTERVAL_S", 3600)
    FakeSlimClient.published = []
    FakeSlimClient.inbox = [l9.serialize(_exchange("backend", ["other"], "not me"))]

    # The one non-addressed message is consumed, then the stream idles — await
    # returns None once the (short) timeout elapses.
    content = await member.await_addressed(_cfg(), "r", "agent-a", timeout_s=0.3)
    assert content is None


def _keepalive(sender: str) -> dict:
    return l9.build_reply_content(
        sender=sender,
        recipients=[],
        episode="urn:ioc:mycelium:episode:r:live",
        parents=[],
        topic="urn:concept:mycelium:r",
        text="",
        payload_type=member.KEEPALIVE_TYPE,
    )


async def _noop_announce(_config: Any, _room: str, _handle: str) -> None:
    return None


class _Applied:
    applied = True
