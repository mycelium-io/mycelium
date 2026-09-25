# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""The addressed hook: an L9 recipient of a turn that named nobody in its text.

The summon hook fires on a mention in the prose; this one fires on the
envelope's recipients, which is how the aligner and the conductor put a
question to one member. A handle is never told twice about one message, and
a signal payload (presence, a ping, a notice) tells nobody anything.
"""

from __future__ import annotations

from app.services import l9, persister
from app.services.l9_models import Kind
from app.services.l9_slim import serialize_content

ROOM = "addressed-room"


def _persister(addressed: list, summoned: list) -> persister.RoomPersister:
    return persister.RoomPersister(
        ROOM,
        channel=None,  # ty: ignore[invalid-argument-type]  # _ingest is called directly
        members_provider=lambda: set(),
        on_summon=lambda handle, env, co, msg="": summoned.append(handle),
        on_addressed=lambda handle, env, msg: addressed.append((handle, msg)),
        feed_bus=False,
    )


def _ingest(
    p: persister.RoomPersister, *, kind=Kind.exchange, payload_type="tick", recipients=(), text=""
):
    env = l9.build_envelope(
        kind=kind,
        subkind="resolved" if kind == Kind.commit else None,
        episode=l9.live_episode_urn(ROOM),
        sender="conductor",
        recipients=list(recipients),
        topic=l9.topic_urn(ROOM),
        payload_type=payload_type,
    )
    p._ingest(env, serialize_content(env, extra={"content": text}), list_write=False)


def test_a_recipient_of_a_turn_is_told_once():
    addressed: list = []
    summoned: list = []
    p = _persister(addressed, summoned)

    _ingest(p, recipients=["sec"], text="approve or block this")

    assert addressed == [("sec", "approve or block this")]
    assert summoned == []


def test_a_mention_is_a_summon_and_not_also_an_address():
    addressed: list = []
    summoned: list = []
    p = _persister(addressed, summoned)

    _ingest(p, recipients=["sec", "api"], text="@sec what do you think?")

    assert summoned == ["sec"]
    assert addressed == [("api", "@sec what do you think?")]


def test_signals_and_commits_address_nobody():
    addressed: list = []
    p = _persister(addressed, [])

    _ingest(p, payload_type="presence", recipients=["sec"])
    _ingest(p, payload_type=l9.PING_PAYLOAD_TYPE, recipients=["sec"])
    _ingest(p, payload_type=l9.NOTICE_PAYLOAD_TYPE, recipients=["sec"])
    _ingest(p, kind=Kind.commit, payload_type="outcome", recipients=["sec"])

    assert addressed == []


def test_no_hook_is_silent():
    p = persister.RoomPersister(
        ROOM,
        channel=None,  # ty: ignore[invalid-argument-type]
        members_provider=lambda: set(),
        feed_bus=False,
    )
    _ingest(p, recipients=["sec"], text="hello")  # must not raise
