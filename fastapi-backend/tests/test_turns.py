# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""One addressed turn: ask one handle, wake only it, take only its answer.

Node-free, over the shared fakes. This is the primitive the aligner brokers
with and a protocol step will ask with; the tests hold its contract rather
than either caller's.
"""

from __future__ import annotations

import asyncio

import pytest

from app.services import l9, turns
from tests.fakes import DEFAULT_ROOM, FakeChannel, FakeManaged, FakePersister, position_record

EPISODE = l9.episode_urn(DEFAULT_ROOM, "e1")
TOPIC = l9.topic_urn(DEFAULT_ROOM)


def _is_position(record) -> bool:
    return record.kind == "exchange" and record.sender not in {"mediator", "system"}


async def _turn(managed, persister, *, handle="a", prompt="@a your move; @b is waiting", **kw):
    return await turns.addressed_turn(
        managed,
        persister,
        sender="mediator",
        handle=handle,
        episode=EPISODE,
        topic=TOPIC,
        prompt=prompt,
        is_reply=_is_position,
        timeout_s=kw.pop("timeout_s", 0.5),
        poll_interval_s=0.01,
        **kw,
    )


def _wired(reply_conf: float | None = 0.9):
    persister = FakePersister()
    channel = FakeChannel(persister, reply_conf=reply_conf)
    return FakeManaged(channel=channel, persister=persister), persister, channel


def test_neutralizing_keeps_the_names_and_drops_the_sigil():
    assert turns.neutralize_mentions("@a, then @b (and @ alone)") == "a, then b (and @ alone)"


@pytest.mark.asyncio
async def test_one_recipient_and_no_sigils_in_the_prose():
    managed, persister, channel = _wired()
    await _turn(managed, persister)

    env, extra = channel.sent[0]
    assert [a.id for a in env.header.participants.actors] == ["mediator", "a"]
    assert extra == {"content": "a your move; b is waiting"}
    assert env.payload.type == "tick"
    # The prompt is in the transcript, so the room can follow along.
    assert persister.ingested[0][1]["content"] == "a your move; b is waiting"


@pytest.mark.asyncio
async def test_the_addressed_handles_reply_comes_back():
    managed, persister, _channel = _wired()
    assert await _turn(managed, persister) == "a position"


@pytest.mark.asyncio
async def test_payload_type_and_data_ride_the_tick():
    managed, persister, channel = _wired()
    await _turn(managed, persister, payload_type="review", payload_data={"step": "gate"})
    env, _extra = channel.sent[0]
    assert env.payload.type == "review"
    assert env.payload.data == {"step": "gate"}


@pytest.mark.asyncio
async def test_silence_yields_nothing():
    managed, persister, _channel = _wired(reply_conf=None)
    assert await _turn(managed, persister, timeout_s=0.05) == ""


@pytest.mark.asyncio
async def test_another_handles_reply_is_not_the_answer():
    managed, persister, _channel = _wired(reply_conf=None)

    async def _b_speaks_then_a():
        await asyncio.sleep(0.02)
        persister.log.record(position_record("b", prose="b butting in"), delivered_to=set())
        await asyncio.sleep(0.02)
        persister.log.record(position_record("a", prose="a, at last"), delivered_to=set())

    task = asyncio.create_task(_b_speaks_then_a())
    assert await _turn(managed, persister) == "a, at last"
    await task


@pytest.mark.asyncio
async def test_a_reply_the_predicate_rejects_is_skipped():
    managed, persister, _channel = _wired(reply_conf=None)
    persister.log.record(position_record("a", role="human", prose="human a"), delivered_to=set())

    def only_agents(record) -> bool:
        actors = record.content["l9"]["header"]["participants"]["actors"]
        return actors[0].get("role") != "human"

    out = await turns.addressed_turn(
        managed,
        persister,
        sender="mediator",
        handle="a",
        episode=EPISODE,
        topic=TOPIC,
        prompt="go",
        is_reply=only_agents,
        timeout_s=0.05,
        poll_interval_s=0.01,
    )
    assert out == ""


@pytest.mark.asyncio
async def test_a_failed_send_is_a_silent_turn():
    class _Down:
        async def send(self, _env, *, extra=None):
            raise RuntimeError("node away")

    persister = FakePersister()
    managed = FakeManaged(channel=_Down(), persister=persister)
    assert await _turn(managed, persister) == ""
    assert persister.ingested == []
