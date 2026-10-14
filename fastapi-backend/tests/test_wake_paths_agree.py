# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""The doorbell, ``await`` and the digest agree on messages nobody wrote down.

``contracts/asks.json`` holds the cases someone thought of. This generates the
rest: a sender and the path it writes through, a payload, recipients, text
built from every way a handle can appear (mentioned, silent, interrupting, in
code, in another case, in an email address), the room or a thread, and an
agent to ask about. Each message is written for real and read back by all
three paths, which must give one answer, the one ``asks()`` gives on what the
transcript recorded.

``MYCELIUM_ASKS_EXAMPLES`` sets how many messages a run tries (a few hundred by
default, to keep the suite fast; the PR that added this ran thousands).
"""

from __future__ import annotations

import os
from typing import Any

import pytest
import pytest_asyncio
from hypothesis import HealthCheck, event, given, settings
from hypothesis import strategies as st

from app.services.asks import asks
from app.services.message_models import Kind
from tests import wake_paths
from tests.wake_paths import AGENT, ENGINES, HERDR, PEER, PERSON, REMOTE, ROOM, Decided

CAST = [AGENT, PEER, PERSON, *ENGINES, REMOTE]
_EXAMPLES = int(os.environ.get("MYCELIUM_ASKS_EXAMPLES", "300"))

_where = st.sampled_from(["room", "thread"])
#: Chat twice as likely as each signal, so most messages could ask someone.
_payload = st.sampled_from(
    ["message", "message", "reply", "reply", "ping", "notice", "presence", "utterance", "outcome"]
)
_words = st.sampled_from(["can you look?", "the parser", "ship it", "thanks", "yes"])


@st.composite
def _case(draw: st.DrawFn) -> tuple[str, dict[str, Any]]:
    """An agent to ask about, and a message that names it half the time a
    handle appears, so asking and not asking are both common."""
    # Mostly an agent with a doorbell, the case all three paths act on.
    agent = draw(st.one_of(st.sampled_from(HERDR), st.sampled_from(CAST)))
    handle = st.one_of(st.just(agent), st.sampled_from(CAST))
    fragment = st.one_of(
        handle.map(lambda h: f"@{h}"),
        handle.map(lambda h: f"@~{h}"),
        handle.map(lambda h: f"@!{h}"),
        handle.map(lambda h: f"`ask @{h}`"),
        handle.map(lambda h: f"@{h.capitalize()}"),
        handle.map(lambda h: f"(@{h})"),
        handle.map(lambda h: f"{h}@example.com"),
        handle.map(lambda h: f"```\n@{h} go\n```"),
        _words,
    )
    text = st.lists(fragment, min_size=1, max_size=4).map(" ".join)
    kind = draw(st.sampled_from(["said", "turn", "posted"]))
    if kind == "turn":
        # The aligner or the conductor putting a step to one or more members.
        message = {
            "sender": draw(st.sampled_from(["aligner", "conductor"])),
            "text": draw(st.one_of(_words, text)),
            "where": draw(_where),
            "payload": "message",
            "to": draw(st.lists(handle, min_size=1, max_size=3, unique=True)),
            "commit": False,
        }
    elif kind == "said":
        # A person posting from the app, or an agent replying through
        # ``respond`` after a turn from someone (or no one).
        message = {
            "sender": draw(st.sampled_from([PERSON, AGENT, PEER])),
            "text": draw(text),
            "where": draw(_where),
            "heard_from": draw(st.one_of(st.none(), handle)),
        }
    else:
        # Anything an engine or a bridge can put on the channel.
        message = {
            "sender": draw(st.sampled_from([*ENGINES, REMOTE])),
            "text": draw(st.one_of(st.just(""), text)),
            "where": draw(_where),
            "payload": draw(_payload),
            "to": draw(st.lists(handle, max_size=3, unique=True)),
            "commit": draw(st.integers(0, 4)) == 0,
        }
    return agent, message


@pytest_asyncio.fixture
async def room(client, monkeypatch) -> wake_paths.Room:
    # One room for every example: each marks what came before as read.
    return await wake_paths.open_room(client, monkeypatch)


async def _write(room: wake_paths.Room, message: dict[str, Any]) -> None:
    if "payload" in message:
        await wake_paths.post(
            room,
            message["sender"],
            message["text"],
            wake_paths.episode_of(room, message["where"]),
            payload=message["payload"],
            to=tuple(message["to"]),
            kind=Kind.commit if message["commit"] else Kind.exchange,
        )
    else:
        heard = message["heard_from"]
        await wake_paths.say(
            room,
            message["sender"],
            message["text"],
            where=message["where"],
            to=(heard,) if heard else (),
        )


@pytest.mark.asyncio
@settings(
    max_examples=_EXAMPLES,
    deadline=None,
    suppress_health_check=[HealthCheck.function_scoped_fixture, HealthCheck.too_slow],
)
@given(case=_case())
async def test_the_paths_agree(room: wake_paths.Room, case: tuple[str, dict]) -> None:
    agent, message = case
    start = wake_paths.mark_read(room, agent)
    await _write(room, message)

    found = {why for r in room.log.records[start:] if (why := asks(r.content, agent, room=ROOM))}
    assert len(found) <= 1
    reason = next(iter(found), None)
    event(f"asks: {reason}")
    got = await wake_paths.decided(room, agent)
    rung = reason if agent in HERDR else None
    assert got == Decided(doorbell=rung, awaited=bool(reason), digest=bool(reason)), message
