# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""
In-process room state: messages, presence, and memory subscriptions.

A deliberately thin, in-memory shim (SLIM-native rebuild, Step 1). These three
concerns lived in Postgres tables (``messages``, ``participants``,
``memory_subscriptions``); with the database gone they move to process memory to
keep the endpoints answering. They are NOT durable and NOT rich — the real
replacements are the SLIM bus + persister in Steps 3-4. Do not build them out
here.

# TODO(step3): messages/presence move onto the SLIM channel + durable persister.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime

# Stable synthetic ids so a room maps to one coordination-session shim and
# repeated (session, handle) joins are idempotent — no database sequence to lean
# on anymore.
_SESSION_NS = uuid.UUID("2b1c0d9e-8f7a-6b5c-4d3e-2f1a0b9c8d7e")
_PARTICIPANT_NS = uuid.UUID("9a8b7c6d-5e4f-3a2b-1c0d-9e8f7a6b5c4d")


def session_id_for_room(room_name: str) -> uuid.UUID:
    """Deterministic coordination-session id for a room's presence shim."""
    return uuid.uuid5(_SESSION_NS, room_name)


def participant_id(session_id: uuid.UUID, handle: str) -> uuid.UUID:
    """Deterministic participant id for a (session, handle) pair."""
    return uuid.uuid5(_PARTICIPANT_NS, f"{session_id}/{handle}")


def _now() -> datetime:
    return datetime.now(UTC)


@dataclass
class CoordSessionShim:
    """Stand-in for the removed ``coordination_sessions`` row.

    Coordination sessions become SLIM channels in Steps 3-4; this only exists so
    the presence endpoints keep their shape. Attribute names mirror the old
    SQLAlchemy model for ``model_validate``.
    """

    parent_room_name: str
    id: uuid.UUID = field(default_factory=uuid.uuid4)
    short_id: str = ""
    state: str = "idle"
    created_at: datetime = field(default_factory=_now)
    join_window_ends_at: datetime | None = None
    mas_id: str | None = None
    workspace_id: str | None = None

    @property
    def display_name(self) -> str:
        return f"{self.parent_room_name}:session:{self.short_id}"


@dataclass
class StoredMessage:
    """In-memory message. Attribute names mirror the old ``Message`` model."""

    sender_handle: str
    message_type: str
    content: str
    room_name: str | None = None
    coordination_session_id: uuid.UUID | None = None
    recipient_handle: str | None = None
    event_metadata: dict | None = None
    event_kind: str | None = None
    event_status: str | None = None
    event_expires_at: datetime | None = None
    id: uuid.UUID = field(default_factory=uuid.uuid4)
    created_at: datetime = field(default_factory=_now)


@dataclass
class StoredParticipant:
    """In-memory presence row. Mirrors the old ``Participant`` model."""

    coordination_session_id: uuid.UUID
    agent_handle: str
    id: uuid.UUID = field(default_factory=uuid.uuid4)
    intent: str | None = None
    context_files: list | None = None
    joined_at: datetime = field(default_factory=_now)
    last_seen: datetime | None = None


@dataclass
class StoredSubscription:
    """In-memory memory-change subscription. Mirrors ``MemorySubscription``."""

    room_name: str
    subscriber: str
    key_pattern: str
    id: uuid.UUID = field(default_factory=uuid.uuid4)
    created_at: datetime = field(default_factory=_now)


# room name → coordination-session shim (one active shim per room)
_sessions: dict[str, CoordSessionShim] = {}
# session id → participants
_participants: dict[uuid.UUID, list[StoredParticipant]] = {}
# room name → messages (session messages are stored under the display name)
_messages: dict[str, list[StoredMessage]] = {}
# room name → subscriptions
_subscriptions: dict[str, list[StoredSubscription]] = {}


def get_or_create_session(room_name: str) -> CoordSessionShim:
    """Return the room's coordination-session shim, creating it on first use."""
    shim = _sessions.get(room_name)
    if shim is None:
        sid = session_id_for_room(room_name)
        shim = CoordSessionShim(
            parent_room_name=room_name, id=sid, short_id=str(sid)[:8], state="idle"
        )
        _sessions[room_name] = shim
    return shim


def get_session(room_name: str) -> CoordSessionShim | None:
    return _sessions.get(room_name)


def add_participant(session_id: uuid.UUID, participant: StoredParticipant) -> None:
    _participants.setdefault(session_id, []).append(participant)


def find_participant(session_id: uuid.UUID, handle: str) -> StoredParticipant | None:
    for p in _participants.get(session_id, []):
        if p.agent_handle == handle:
            return p
    return None


def list_participants(session_id: uuid.UUID) -> list[StoredParticipant]:
    return list(_participants.get(session_id, []))


def remove_participant(session_id: uuid.UUID, participant_pk: uuid.UUID) -> bool:
    roster = _participants.get(session_id)
    if not roster:
        return False
    for i, p in enumerate(roster):
        if p.id == participant_pk:
            del roster[i]
            return True
    return False


def add_message(channel_name: str, message: StoredMessage) -> None:
    _messages.setdefault(channel_name, []).append(message)


def list_messages(channel_name: str) -> list[StoredMessage]:
    return list(_messages.get(channel_name, []))


def find_message(message_id: uuid.UUID) -> StoredMessage | None:
    for msgs in _messages.values():
        for m in msgs:
            if m.id == message_id:
                return m
    return None


def sweep_expired_messages(now: datetime) -> int:
    """Drop messages past their ``event_expires_at``. Returns count removed."""
    removed = 0
    for msgs in _messages.values():
        keep = []
        for m in msgs:
            if m.event_expires_at is not None and m.event_expires_at < now:
                removed += 1
            else:
                keep.append(m)
        msgs[:] = keep
    return removed


def add_subscription(sub: StoredSubscription) -> None:
    _subscriptions.setdefault(sub.room_name, []).append(sub)


def list_subscriptions(room_name: str) -> list[StoredSubscription]:
    return list(_subscriptions.get(room_name, []))


def remove_subscription(room_name: str, sub_id: uuid.UUID) -> bool:
    subs = _subscriptions.get(room_name)
    if not subs:
        return False
    for i, s in enumerate(subs):
        if s.id == sub_id:
            del subs[i]
            return True
    return False


def clear_all() -> None:
    """Reset all in-memory state. Used by tests to isolate cases."""
    _sessions.clear()
    _participants.clear()
    _messages.clear()
    _subscriptions.clear()
