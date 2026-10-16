# Copyright 2026 Cisco Systems, Inc. and its affiliates
#
# SPDX-License-Identifier: Apache-2.0

# Mycelium's message models: the shape of every message the hub records.

from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field, RootModel


class MessageSchema(RootModel[Any]):
    root: Any = Field(
        ...,
        description="Combined JSON Schema for the message models.",
        title="MessageSchema",
    )


class Actor(BaseModel):
    id: str = Field(..., title="Id")
    role: str = Field(..., title="Role")
    attestation: str | None = Field(None, title="Attestation")


class Epistemic(BaseModel):
    pass


class Provenance(BaseModel):
    pass


class Semantic(BaseModel):
    schema_id: str = Field(..., title="Schema Id")
    ontology_ref: str = Field(..., title="Ontology Ref")
    provenance: Provenance | None = None


class Context(BaseModel):
    topic: str = Field(..., title="Topic")
    epistemic: Epistemic | None = None
    semantic: Semantic | None = None


class MessageRef(BaseModel):
    id: str = Field(..., title="Id")
    parents: list[str] = Field(
        ...,
        description="Ordered list of parent message IDs. Empty list for root messages.",
        title="Parents",
    )
    episode: str = Field(..., title="Episode")


class Episode(BaseModel):
    id: str = Field(..., title="Id")
    messages: list[MessageRef] = Field(..., title="Messages")


class ParticipantSet(BaseModel):
    actors: list[Actor] = Field(..., title="Actors")
    groups: dict[str, Any] | None = Field(..., title="Groups")


class PolicyLabel(BaseModel):
    sensitivity: str = Field(..., title="Sensitivity")
    propagation: str = Field(..., title="Propagation")
    retention_policy: str = Field(..., title="Retention Policy")


class TaskWork(BaseModel):
    id: str = Field(..., title="Id")
    assigned_to: str = Field(..., title="Assigned To")
    task_description: str = Field(..., title="Task Description")
    status: str = Field(..., title="Status")
    episodes: list[Episode] = Field(..., title="Episodes")


class Team(BaseModel):
    id: str = Field(..., title="Id")
    team_members: list[str] = Field(..., title="Team Members")
    tasks: list[TaskWork] = Field(..., title="Tasks")


class Kind(Enum):
    intent = "intent"
    contingency = "contingency"
    exchange = "exchange"
    commit = "commit"
    knowledge = "knowledge"


class MessageHeader(BaseModel):
    protocol: str = Field(..., title="Protocol")
    subprotocol: str = Field(..., title="Subprotocol")
    version: str = Field(..., title="Version")
    kind: Kind
    subkind: str | None = Field(None, title="Subkind")
    participants: ParticipantSet
    message: MessageRef | None = None
    policy: PolicyLabel | None = None
    attributes: dict[str, Any] | None = Field(None, title="Attributes")
    context: Context | None = None


class MessagePayload(BaseModel):
    type: str = Field(..., title="Type")
    data: dict[str, Any] = Field(..., title="Data")


class MyceliumMessage(BaseModel):
    header: MessageHeader
    payload: MessagePayload
