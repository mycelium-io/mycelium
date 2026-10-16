# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""The asked hook: the persister tells the room who each message asks, and why.

It fires once per handle a recorded message asks (``app.services.asks``):
a mention, an interrupt, or a turn put to a message recipient, which is how
the aligner and the conductor put a question to one member. A handle is never
told twice about one message, and a signal payload (presence, a ping, a
notice) or a commit tells nobody anything.
"""

from __future__ import annotations

from app.services import message_format, persister
from app.services.message_models import Kind
from app.services.message_slim import serialize_content

ROOM = "addressed-room"


def _persister(asked: list, summoned: list) -> persister.RoomPersister:
    return persister.RoomPersister(
        ROOM,
        channel=None,  # ty: ignore[invalid-argument-type]  # _ingest is called directly
        members_provider=lambda: set(),
        on_summon=lambda handle, env, co, msg="": summoned.append(handle),
        on_asked=lambda handle, why, env, msg: asked.append((handle, why, msg)),
        feed_bus=False,
    )


def _ingest(
    p: persister.RoomPersister,
    *,
    kind=Kind.exchange,
    payload_type="message",
    recipients=(),
    text="",
):
    env = message_format.build_envelope(
        kind=kind,
        subkind="resolved" if kind == Kind.commit else None,
        episode=message_format.live_episode_urn(ROOM),
        sender="conductor",
        recipients=list(recipients),
        topic=message_format.topic_urn(ROOM),
        payload_type=payload_type,
    )
    p._ingest(env, serialize_content(env, extra={"content": text}), list_write=False)


def test_a_recipient_of_a_turn_is_told_once():
    asked: list = []
    summoned: list = []
    p = _persister(asked, summoned)

    _ingest(p, recipients=["sec"], text="approve or block this")

    assert asked == [("sec", "turn", "approve or block this")]
    assert summoned == []


def test_a_mention_is_a_summon_and_asks_as_a_mention_not_also_a_turn():
    asked: list = []
    summoned: list = []
    p = _persister(asked, summoned)

    _ingest(p, recipients=["sec", "api"], text="@sec what do you think?")

    assert summoned == ["sec"]
    assert asked == [
        ("sec", "mention", "@sec what do you think?"),
        ("api", "turn", "@sec what do you think?"),
    ]


def test_signals_and_commits_ask_nobody():
    asked: list = []
    p = _persister(asked, [])

    _ingest(p, payload_type="presence", recipients=["sec"], text="here")
    _ingest(p, payload_type=message_format.PING_PAYLOAD_TYPE, recipients=["sec"], text="moved")
    _ingest(p, payload_type=message_format.NOTICE_PAYLOAD_TYPE, recipients=["sec"], text="filed")
    _ingest(p, kind=Kind.commit, payload_type="outcome", recipients=["sec"], text="@sec agreed")

    assert asked == []


def test_a_reply_asks_only_whoever_it_mentions():
    # An agent answering a person names, as its recipient, whoever it last
    # heard from, here another agent. That agent wasn't asked anything: no
    # doorbell, and no persona or worker answering. Asking takes a mention.
    asked: list = []
    summoned: list = []
    p = _persister(asked, summoned)

    _ingest(p, payload_type="reply", recipients=["coder"], text="Yes, that command works.")
    assert asked == []

    _ingest(p, payload_type="reply", recipients=["coder"], text="@coder can you take it?")
    assert summoned == ["coder"]
    assert asked == [("coder", "mention", "@coder can you take it?")]


def test_no_hook_is_silent():
    p = persister.RoomPersister(
        ROOM,
        channel=None,  # ty: ignore[invalid-argument-type]
        members_provider=lambda: set(),
        feed_bus=False,
    )
    _ingest(p, recipients=["sec"], text="hello")  # must not raise
