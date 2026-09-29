# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""
L9 (IOC / SSTP) envelope construction and validation.

L9 is the Internet-of-Cognition epistemic protocol layer
(outshift-open/ioc-protocols-models). Every L9 message is an envelope:
a fixed header (kind/subkind, participants, episode URN, message id +
causal parents, topic) plus a typed payload.

Mycelium uses L9 two ways:

1. Coordination messages (ticks, replies, consensus) carry an ``l9`` key
   inside their existing content JSON. This is additive: agents and UIs
   that ignore it keep working unchanged.
2. The Go CFN service (outshift-open/ioc-cfn-svc) exposes a native
   ``POST /api/l9/messages`` endpoint that routes envelopes to Cognition
   Engines by kind/subkind. ``l9_cfn.py`` posts envelopes built here.

In the subkind vocabulary below, a failed negotiation commits as ``rejected``.
"""

from __future__ import annotations

import json
import uuid
from typing import Any

from app.services.l9_models import (
    L9,
    Actor,
    Context,
    Kind,
    L9Header,
    L9Payload,
    Message,
    ParticipantSet,
)

PROTOCOL = "SSTP"
VERSION = "0.0.6"  # tracks the ioc-protocols-models binding the Go CFN pins
SUBPROTOCOL_MYCELIUM = "mycelium"

# The handle mycelium's *backend itself* speaks as inside envelopes — genuine
# system messages (plan-updated events, joins, knowledge distillation, aborts),
# not a coordination engine. A registered engine (e.g. the aligner) signs its own
# envelopes with its engine handle; only messages with no engine author fall back
# to this. Matches the sender_handle used for coordination system messages.
SYSTEM_ACTOR_ID = "system"
SYSTEM_ACTOR_ROLE = "coordinator"

# ``exchange`` move subkinds: the closed vocabulary a coordination reply carries
# so a negotiation move is explicit on the wire (countable, replayable) instead
# of inferred from prose. ``counter`` is any offer (the opening one included);
# ``accept``/``reject`` respond to the standing offer. The mediator emits exactly
# these (``mediator.interpret``). A reply with no subkind stays valid, so replies
# predating this vocabulary round-trip unchanged.
EXCHANGE_MOVE_SUBKINDS = frozenset({"counter", "accept", "reject"})

# An ``exchange:amend`` revises an earlier message: its ``message.parents``
# carries the id of the message it revises and its payload carries the new text.
# Nothing in the transcript is rewritten — every version stays a recorded event —
# and the read path folds a message and its amendments into the newest text
# (:func:`app.services.persister.collapse_amendments`).
AMEND_SUBKIND = "amend"

# Kind -> allowed subkinds. An empty/None subkind is always valid. A failed
# negotiation commits as ``rejected``.
VALID_SUBKINDS: dict[Kind, frozenset[str]] = {
    Kind.knowledge: frozenset({"query", "distillation", "extraction", "feedback"}),
    Kind.commit: frozenset({"converged", "resolved", "rejected"}),
    Kind.intent: frozenset({"coordinator-assignment", "mission"}),
    Kind.exchange: frozenset({"team-formation", AMEND_SUBKIND}) | EXCHANGE_MOVE_SUBKINDS,
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
#: anyone (:func:`app.routes.participate._addressed_to`).
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
#: ``contracts/slim-l9-wire.json``. ``filed`` also carries the row's board
#: ``kind`` (so the line reads "New decision", not always "New task") and who it
#: is ``for``; the custody and lifecycle subkinds carry ``by`` (who moved it).
#: ``expired`` is the one nobody writes: a held lease drained by the clock, and
#: ``by`` names the holder who stopped renewing it. ``floor`` says whose turn it
#: is in a thread (:mod:`app.services.floor`): ``key`` is the thread's short id,
#: ``by`` the holder, ``speakers`` the comma-joined handles it was given to, and
#: ``released`` marks the floor opening back up.
NOTICE_SUBKINDS = frozenset(
    {"filed", "claimed", "released", "resolved", "blocked", "unblocked", "expired", "floor"}
)


class L9ValidationError(ValueError):
    """An envelope violates the L9 structure or the CFN subkind table."""


def episode_urn(parent_room: str, session_id: str) -> str:
    """Mint the episode URN scoping all messages of one coordination session."""
    return f"urn:ioc:mycelium:episode:{parent_room}:{session_id}"


def live_episode_urn(parent_room: str) -> str:
    """The URN of the room's own channel — where a message with no thread lands."""
    return episode_urn(parent_room, LIVE_SESSION)


def is_live_episode(parent_room: str, episode: str | None) -> bool:
    """Whether ``episode`` is the room itself rather than a thread inside it.

    ``None`` is the room: a caller that names no thread is talking to the room.
    """
    return episode is None or episode == live_episode_urn(parent_room)


def topic_urn(parent_room: str) -> str:
    """The concept URI a room's negotiations are about."""
    return f"urn:concept:mycelium:{parent_room}"


def validate_subkind(kind: Kind, subkind: str | None) -> None:
    """Reject subkinds outside the allowed table for this kind."""
    if not subkind:
        return
    allowed = VALID_SUBKINDS.get(kind, frozenset())
    if subkind not in allowed:
        raise L9ValidationError(
            f"invalid subkind {subkind!r} for kind={kind.value} (allowed: {sorted(allowed)})"
        )


# The v0.0.6 binding has no participant_type field on Actor; by convention
# (matching the hcpanel reference implementation's bus) the first actor in the
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
) -> L9:
    """Build a validated L9 envelope.

    ``workspace_id``/``mas_id`` land in ``participants.groups``: the Go CFN's
    content-based routing extracts them from there, so both are required for
    envelopes that will be POSTed to the CFN (optional for envelopes that only
    annotate mycelium's own coordination messages).
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

    return L9(
        header=L9Header(
            protocol=PROTOCOL,
            subprotocol=SUBPROTOCOL_MYCELIUM,
            version=VERSION,
            kind=kind,
            subkind=subkind,
            participants=ParticipantSet(actors=actors, groups=groups),
            message=Message(
                id=message_id or str(uuid.uuid4()),
                parents=parents or [],
                episode=episode,
            ),
            context=Context(topic=topic) if topic else None,
        ),
        payload=L9Payload(type=payload_type, data=payload_data or {}),
    )


def envelope_to_dict(envelope: L9) -> dict[str, Any]:
    """Serialize for embedding in a message's content JSON (drops None keys)."""
    data = envelope.model_dump(mode="json", exclude_none=True)
    # participants.groups is required-but-nullable in the schema; exclude_none
    # would drop it and break re-validation, so restore an explicit null.
    data["header"]["participants"].setdefault("groups", None)
    return data


def parse_envelope(raw: dict[str, Any] | str) -> L9:
    """Parse and validate an envelope from content JSON (raises on invalid)."""
    if isinstance(raw, str):
        raw = json.loads(raw)
    envelope = L9.model_validate(raw)
    validate_subkind(envelope.header.kind, envelope.header.subkind)
    return envelope


def extract_parent_id(content: str | dict[str, Any]) -> str | None:
    """Pull the L9 message id out of a coordination message's content, if any.

    Used to thread causality: a reply's envelope lists the tick's id in
    ``message.parents``; the consensus lists the final replies' ids.
    """
    try:
        data = json.loads(content) if isinstance(content, str) else content
        return data["l9"]["header"]["message"]["id"]
    except (json.JSONDecodeError, KeyError, TypeError):
        return None
