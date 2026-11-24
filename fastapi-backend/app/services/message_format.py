# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""
The message format: construction and validation.

Every message on a room's channel carries an envelope: a fixed header
(kind/subkind, participants, episode URN, message id + causal parents, topic)
plus a typed payload. It is how the hub labels and records what passes through
a room, which is what the Network pane shows.

A message's content JSON carries its envelope under the ``envelope`` key. The
key is additive: agents and UIs that ignore it keep working.

In the subkind vocabulary below, a failed negotiation commits as ``rejected``.
"""

from __future__ import annotations

import json
import uuid
from typing import Any

from app.services.message_models import (
    Actor,
    Context,
    Kind,
    MessageHeader,
    MessagePayload,
    MessageRef,
    MyceliumMessage,
    ParticipantSet,
)

#: The key a message's envelope sits under inside its content JSON.
CONTENT_ENVELOPE_KEY = "envelope"
#: The key older records carry their envelope under; read, never written.
LEGACY_CONTENT_ENVELOPE_KEY = "l9"
#: How a frame that carries a whole recorded envelope names its type:
#: ``envelope_<kind>`` (``envelope_exchange``, ``envelope_knowledge``, ...).
FRAME_TYPE_PREFIX = "envelope_"

#: What a message's header names its format and version as.
PROTOCOL = "MYCP"
VERSION = "1.0.0"
SUBPROTOCOL_MYCELIUM = "mycelium"

#: How an episode's URN starts: ``urn:mycelium:episode:{room}:{id}``.
EPISODE_URN_PREFIX = "urn:mycelium:episode:"
#: How a room's topic URN starts: ``urn:mycelium:topic:{room}``.
TOPIC_URN_PREFIX = "urn:mycelium:topic:"
#: The prefixes rooms recorded before these, rewritten to the ones above by
#: the ``mycelium-3.1-names`` migration and when a client still sends one.
LEGACY_URN_PREFIXES = {
    "urn:ioc:mycelium:episode:": EPISODE_URN_PREFIX,
    "urn:concept:mycelium:": TOPIC_URN_PREFIX,
}

# The handle mycelium's *backend itself* speaks as inside envelopes — genuine
# system messages (plan-updated events, joins, knowledge distillation, aborts),
# not a coordination engine. A registered engine (e.g. the conductor) signs its own
# envelopes with its engine handle; only messages with no engine author fall back
# to this. Matches the sender_handle used for coordination system messages.
SYSTEM_ACTOR_ID = "system"
SYSTEM_ACTOR_ROLE = "coordinator"

# ``exchange`` move subkinds: the closed vocabulary a coordination reply carries
# so a negotiation move is explicit on the wire (countable, replayable) instead
# of inferred from prose. ``counter`` is any offer (the opening one included);
# ``accept``/``reject`` respond to the standing offer. No hub engine emits these
# today. A reply with no subkind stays valid, so replies predating this
# vocabulary round-trip unchanged.
EXCHANGE_MOVE_SUBKINDS = frozenset({"counter", "accept", "reject"})

# An ``exchange:amend`` revises an earlier message: its ``message.parents``
# carries the id of the message it revises and its payload carries the new text.
# Nothing in the transcript is rewritten — every version stays a recorded event —
# and the read path folds a message and its amendments into the newest text
# (:func:`app.services.persister.collapse_amendments`).
AMEND_SUBKIND = "amend"

# An ``exchange:reaction`` puts an emoji on an earlier message, or takes one off.
# Its ``message.parents`` carries the id of the message it reacts to, and its
# content carries ``reaction: {emoji, on}``. Its text silently mentions the
# message's author (``@~author 👍``), so the author reads it on their next wake
# and nobody is woken. The read path folds every reaction into the message it is
# on (:func:`app.services.persister.collapse_reactions`).
REACTION_SUBKIND = "reaction"

# Kind -> allowed subkinds. An empty/None subkind is always valid. A failed
# negotiation commits as ``rejected``.
VALID_SUBKINDS: dict[Kind, frozenset[str]] = {
    Kind.knowledge: frozenset({"query", "distillation", "extraction", "feedback"}),
    Kind.commit: frozenset({"converged", "resolved", "rejected"}),
    Kind.intent: frozenset({"coordinator-assignment", "mission"}),
    Kind.exchange: frozenset({"team-formation", AMEND_SUBKIND, REACTION_SUBKIND})
    | EXCHANGE_MOVE_SUBKINDS,
    Kind.contingency: frozenset({"negotiation"}),
}


#: The session id of a room's own channel — the episode everything said *to the
#: room* rides under, as opposed to a thread inside it. A task's thread
#: and a negotiation are episodes too; ``live`` is the one that is the room.
LIVE_SESSION = "live"

#: The payload type of a **ping**: the compact signal raised into ``live`` saying
#: a thread moved, carrying no echo of what was said. It sits beside
#: ``presence``/``keepalive`` as a control payload — deliberately not chat, and
#: deliberately not an addressed turn, so it surfaces activity without waking
#: anyone (:func:`app.services.asks.asks`).
PING_PAYLOAD_TYPE = "ping"

#: The payload type of a **notice**: the room's timeline of what happened to its
#: work — a task filed, claimed, handed back or resolved. Like a ping it is a
#: control payload raised into ``live`` that wakes nobody, but where a ping says a
#: thread *moved*, a notice says the *board* moved: it names the task, carries the
#: line the room reads ("New task", "@x is on it", "resolved"), and never the
#: prose (which stays in the thread). ``data.subkind`` is one of
#: :data:`NOTICE_SUBKINDS`; the rest of ``data`` is the task it is about.
NOTICE_PAYLOAD_TYPE = "notice"

#: What a notice can be about, as a closed set frozen in
#: ``contracts/message-wire.json``. ``filed`` also carries the row's board
#: ``kind`` (so the line reads "New decision", not always "New task") and who it
#: is ``for``; the custody and lifecycle subkinds carry ``by`` (who moved it).
#: ``expired`` is the one nobody writes: a held lease drained by the clock, and
#: ``by`` names the holder who stopped renewing it. ``floor`` says whose turn it
#: is in a thread (:mod:`app.services.floor`): ``key`` is the thread's short id,
#: ``by`` the holder, ``speakers`` the comma-joined handles it was given to, and
#: ``released`` marks the floor opening back up. ``upstream`` says the thing a
#: row points at changed outside the room (a pull request's review or CI moved,
#: or it merged): ``change`` is one of :data:`UPSTREAM_CHANGES`, and nobody but
#: the status watcher (:mod:`app.services.status.watch`) raises it. ``check`` is
#: about a message, not a task: the verifier (:mod:`app.services.verifier`)
#: couldn't confirm a claim in it, and ``message_id`` names the message.
NOTICE_SUBKINDS = frozenset(
    {
        "filed",
        "claimed",
        "released",
        "resolved",
        "blocked",
        "unblocked",
        "expired",
        "quiet",
        "floor",
        "upstream",
        "check",
    }
)

#: What an ``upstream`` notice can say happened, frozen beside the subkinds.
UPSTREAM_CHANGES = frozenset(
    {
        "opened",
        "review_requested",
        "approved",
        "changes_requested",
        "ci_failed",
        "ci_passed",
        "merged",
        "closed",
    }
)


class MessageValidationError(ValueError):
    """A message violates the header structure or the subkind table."""


def episode_urn(parent_room: str, session_id: str) -> str:
    """Mint the episode URN scoping all messages of one coordination session."""
    return f"{EPISODE_URN_PREFIX}{parent_room}:{session_id}"


def canonical_urn(urn: str) -> str:
    """``urn`` with a legacy prefix (:data:`LEGACY_URN_PREFIXES`) replaced by
    the current one; any other string as it is."""
    for old, new in LEGACY_URN_PREFIXES.items():
        if urn.startswith(old):
            return new + urn[len(old) :]
    return urn


def live_episode_urn(parent_room: str) -> str:
    """The URN of the room's own channel — where a message with no thread lands."""
    return episode_urn(parent_room, LIVE_SESSION)


def is_live_episode(parent_room: str, episode: str | None) -> bool:
    """Whether ``episode`` is the room itself rather than a thread inside it.

    ``None`` is the room: a caller that names no thread is talking to the room.
    """
    return episode is None or canonical_urn(episode) == live_episode_urn(parent_room)


def topic_urn(parent_room: str) -> str:
    """The URN of what a room's messages are about: the room."""
    return f"{TOPIC_URN_PREFIX}{parent_room}"


def validate_subkind(kind: Kind, subkind: str | None) -> None:
    """Reject subkinds outside the allowed table for this kind."""
    if not subkind:
        return
    allowed = VALID_SUBKINDS.get(kind, frozenset())
    if subkind not in allowed:
        raise MessageValidationError(
            f"invalid subkind {subkind!r} for kind={kind.value} (allowed: {sorted(allowed)})"
        )


# An Actor carries no participant type; by convention the first actor in the
# list is the sender and the rest are recipients.


def build_envelope(
    *,
    kind: Kind,
    subkind: str | None = None,
    episode: str,
    parents: list[str] | None = None,
    sender: str = SYSTEM_ACTOR_ID,
    sender_role: str = SYSTEM_ACTOR_ROLE,
    recipients: list[str] | None = None,
    recipient_role: str = "agent",
    topic: str | None = None,
    workspace_id: str | None = None,
    mas_id: str | None = None,
    payload_type: str = "data",
    payload_data: dict[str, Any] | None = None,
    message_id: str | None = None,
) -> MyceliumMessage:
    """Build a validated message.

    ``workspace_id``/``mas_id``, when given, land in ``participants.groups``.
    """
    validate_subkind(kind, subkind)

    actors = [Actor(id=sender, role=sender_role)]
    actors += [Actor(id=r, role=recipient_role) for r in (recipients or [])]

    groups: dict[str, Any] | None = None
    if workspace_id or mas_id:
        groups = {}
        if workspace_id:
            groups["workspace_id"] = workspace_id
        if mas_id:
            groups["mas_id"] = mas_id

    return MyceliumMessage(
        header=MessageHeader(
            protocol=PROTOCOL,
            subprotocol=SUBPROTOCOL_MYCELIUM,
            version=VERSION,
            kind=kind,
            subkind=subkind,
            participants=ParticipantSet(actors=actors, groups=groups),
            message=MessageRef(
                id=message_id or str(uuid.uuid4()),
                parents=parents or [],
                episode=episode,
            ),
            context=Context(topic=topic) if topic else None,
        ),
        payload=MessagePayload(type=payload_type, data=payload_data or {}),
    )


def envelope_to_dict(envelope: MyceliumMessage) -> dict[str, Any]:
    """Serialize for embedding in a message's content JSON (drops None keys)."""
    data = envelope.model_dump(mode="json", exclude_none=True)
    # participants.groups is required-but-nullable in the schema; exclude_none
    # would drop it and break re-validation, so restore an explicit null.
    data["header"]["participants"].setdefault("groups", None)
    return data


def serialize_content(
    envelope: MyceliumMessage, *, extra: dict[str, Any] | None = None
) -> dict[str, Any]:
    """The content a message is recorded as: ``extra`` (its text and any
    payload fields) with the envelope under :data:`CONTENT_ENVELOPE_KEY`."""
    content: dict[str, Any] = dict(extra or {})
    content[CONTENT_ENVELOPE_KEY] = envelope_to_dict(envelope)
    return content


def envelope_of(content: dict[str, Any]) -> dict[str, Any]:
    """The envelope inside a message's content dict, or ``{}`` if it has none.

    Reads :data:`CONTENT_ENVELOPE_KEY`, then :data:`LEGACY_CONTENT_ENVELOPE_KEY`
    for a record written before the key was renamed.
    """
    env = content.get(CONTENT_ENVELOPE_KEY) or content.get(LEGACY_CONTENT_ENVELOPE_KEY)
    return env if isinstance(env, dict) else {}


def frame_type(kind: str) -> str:
    """The ``message_type`` a recorded envelope of ``kind`` rides as on a frame."""
    return f"{FRAME_TYPE_PREFIX}{kind}"


def parse_envelope(raw: dict[str, Any] | str) -> MyceliumMessage:
    """Parse and validate an envelope from content JSON (raises on invalid)."""
    if isinstance(raw, str):
        raw = json.loads(raw)
    envelope = MyceliumMessage.model_validate(raw)
    validate_subkind(envelope.header.kind, envelope.header.subkind)
    return envelope


def extract_parent_id(content: str | dict[str, Any]) -> str | None:
    """Pull the message id out of a coordination message's content, if any.

    Used to thread causality: a reply's envelope lists the tick's id in
    ``message.parents``; the consensus lists the final replies' ids.
    """
    try:
        data = json.loads(content) if isinstance(content, str) else content
        return envelope_of(data)["header"]["message"]["id"]
    except (json.JSONDecodeError, KeyError, TypeError, AttributeError):
        return None
