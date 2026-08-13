# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""Unit tests for the in-memory room-state shim (app/services/local_state.py).

Node-free and DB-free: this is the process-memory stand-in for the removed
``messages`` / ``participants`` / ``memory_subscriptions`` tables, so it's pure
Python. ``conftest`` resets the module-global maps between tests.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.services import local_state as ls


def test_deterministic_ids_are_stable_and_idempotent() -> None:
    """A room maps to one session id; a (session, handle) pair to one participant id."""
    sid = ls.session_id_for_room("room-a")
    assert sid == ls.session_id_for_room("room-a")  # stable across calls
    assert sid != ls.session_id_for_room("room-b")  # per-room
    pid = ls.participant_id(sid, "agent-a")
    assert pid == ls.participant_id(sid, "agent-a")
    assert pid != ls.participant_id(sid, "agent-b")


def test_get_or_create_session_is_idempotent() -> None:
    first = ls.get_or_create_session("room-a")
    assert ls.get_or_create_session("room-a") is first  # same shim, not a new one
    assert ls.get_session("room-a") is first
    assert ls.get_session("never") is None
    assert first.short_id == str(first.id)[:8]


def test_participant_add_find_list_remove() -> None:
    sid = ls.session_id_for_room("room-a")
    p = ls.StoredParticipant(coordination_session_id=sid, agent_handle="agent-a")
    ls.add_participant(sid, p)

    assert ls.find_participant(sid, "agent-a") is p
    assert ls.find_participant(sid, "ghost") is None
    assert ls.list_participants(sid) == [p]

    assert ls.remove_participant(sid, p.id) is True
    assert ls.remove_participant(sid, p.id) is False  # already gone
    assert ls.list_participants(sid) == []


def test_message_add_list_find() -> None:
    msg = ls.StoredMessage(sender_handle="a", message_type="broadcast", content="hi")
    ls.add_message("room-a", msg)

    assert ls.list_messages("room-a") == [msg]
    assert ls.list_messages("empty") == []
    assert ls.find_message(msg.id) is msg
    assert ls.find_message(ls.uuid.uuid4()) is None


def test_sweep_drops_only_expired_messages() -> None:
    now = datetime.now(UTC)
    durable = ls.StoredMessage(sender_handle="a", message_type="broadcast", content="keep")
    expired = ls.StoredMessage(
        sender_handle="a",
        message_type="event",
        content="gone",
        event_expires_at=now - timedelta(seconds=1),
    )
    future = ls.StoredMessage(
        sender_handle="a",
        message_type="event",
        content="stay",
        event_expires_at=now + timedelta(hours=1),
    )
    for m in (durable, expired, future):
        ls.add_message("room-a", m)

    removed = ls.sweep_expired_messages(now)
    assert removed == 1
    remaining = {m.content for m in ls.list_messages("room-a")}
    assert remaining == {"keep", "stay"}  # durable (no TTL) + not-yet-expired survive


def test_subscription_add_list_remove() -> None:
    sub = ls.StoredSubscription(room_name="room-a", subscriber="agent-a", key_pattern="decisions/*")
    ls.add_subscription(sub)

    assert ls.list_subscriptions("room-a") == [sub]
    assert ls.remove_subscription("room-a", sub.id) is True
    assert ls.remove_subscription("room-a", sub.id) is False
    assert ls.list_subscriptions("room-a") == []


def test_clear_all_resets_every_map() -> None:
    sid = ls.session_id_for_room("room-a")
    ls.get_or_create_session("room-a")
    ls.add_participant(sid, ls.StoredParticipant(coordination_session_id=sid, agent_handle="a"))
    ls.add_message("room-a", ls.StoredMessage(sender_handle="a", message_type="b", content="c"))
    ls.add_subscription(ls.StoredSubscription(room_name="room-a", subscriber="a", key_pattern="*"))

    ls.clear_all()

    assert ls.get_session("room-a") is None
    assert ls.list_participants(sid) == []
    assert ls.list_messages("room-a") == []
    assert ls.list_subscriptions("room-a") == []
