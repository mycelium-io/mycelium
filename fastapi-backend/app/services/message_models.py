# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""The shape of a message the hub records: a header and a payload.

Built by :func:`app.services.message_format.build_envelope` and read back by
:func:`app.services.message_format.parse_envelope`. Fields the hub never sets
are left out; a stored message that carries others still reads, since unknown
fields are ignored.
"""

from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class Kind(Enum):
    """What a message is: the kinds the subkind table
    (``message_format.VALID_SUBKINDS``) is keyed by."""

    intent = "intent"
    contingency = "contingency"
    exchange = "exchange"
    commit = "commit"
    knowledge = "knowledge"


class Actor(BaseModel):
    """Someone a message is from or to: a handle and the role it speaks in."""

    id: str
    role: str


class ParticipantSet(BaseModel):
    """Who a message involves: its sender first, then its recipients."""

    actors: list[Actor]
    groups: dict[str, Any] | None = Field(...)


class MessageRef(BaseModel):
    """A message's id, the ids it answers, and the episode it belongs to."""

    id: str
    parents: list[str] = Field(..., description="Parent message ids; empty for a root message.")
    episode: str


class Context(BaseModel):
    """What a message is about: the room's topic URN."""

    topic: str


class MessageHeader(BaseModel):
    """Everything about a message except what it carries."""

    protocol: str
    subprotocol: str
    version: str
    kind: Kind
    subkind: str | None = None
    participants: ParticipantSet
    message: MessageRef | None = None
    context: Context | None = None


class MessagePayload(BaseModel):
    """What a message carries: a type and its data."""

    type: str
    data: dict[str, Any]


class MyceliumMessage(BaseModel):
    """One recorded message's envelope."""

    header: MessageHeader
    payload: MessagePayload
