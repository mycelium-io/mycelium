# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Julia Valenti

"""
Minimal schemas for Mycelium's core models.
"""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field

# ── Room ──────────────────────────────────────────────────────────────────────


class RoomCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    description: str | None = Field(None, max_length=500)
    is_public: bool = True
    trigger_config: dict | None = None
    mas_id: str | None = None
    workspace_id: str | None = None


class RoomRead(BaseModel):
    id: int
    name: str
    description: str | None = None
    is_public: bool
    created_at: datetime
    coordination_state: str = "idle"
    join_deadline: datetime | None = None
    mode: str = "sync"
    trigger_config: dict | None = None
    last_synthesis_at: datetime | None = None
    is_persistent: bool = False
    is_namespace: bool = False
    parent_namespace: str | None = None
    mas_id: str | None = None
    workspace_id: str | None = None

    model_config = {"from_attributes": True}


# ── Message ───────────────────────────────────────────────────────────────────


class MessageType:
    ANNOUNCE = "announce"
    DIRECT = "direct"
    BROADCAST = "broadcast"
    DELEGATE = "delegate"
    # Coordination system messages (posted directly by coordination service, not via HTTP API)
    COORDINATION_JOIN = "coordination_join"
    COORDINATION_START = "coordination_start"
    COORDINATION_TICK = "coordination_tick"
    COORDINATION_CONSENSUS = "coordination_consensus"


class MessageCreate(BaseModel):
    sender_handle: str = Field(..., description="Sender handle (e.g., 'alpha#a8f3')")
    recipient_handle: str | None = Field(
        None, description="Recipient handle for direct messages; omit for broadcast"
    )
    message_type: str = Field(
        ...,
        description="Type: announce, direct, broadcast, or delegate",
        pattern="^(announce|direct|broadcast|delegate)$",
    )
    content: str = Field(..., min_length=1)


class MessageRead(BaseModel):
    id: UUID
    room_name: str
    sender_handle: str
    recipient_handle: str | None = None
    message_type: str
    content: str
    created_at: datetime

    model_config = {"from_attributes": True}


class MessageListResponse(BaseModel):
    messages: list[MessageRead]
    total: int


# ── Session ───────────────────────────────────────────────────────────────────


class SessionCreate(BaseModel):
    agent_handle: str = Field(..., description="Agent handle joining the room")
    intent: str | None = Field(None, description="Agent's requirements/intent for coordination")


class SessionRead(BaseModel):
    id: UUID
    room_name: str
    agent_handle: str
    intent: str | None = None
    joined_at: datetime
    last_seen: datetime | None = None

    model_config = {"from_attributes": True}


class SessionListResponse(BaseModel):
    sessions: list[SessionRead]
    total: int


# ── AuditEvent ────────────────────────────────────────────────────────────────

VALID_RESOURCE_TYPES = {
    "COGNITIVE_ENGINE",
    "POLICY_ENFORCER",
    "MEMORY_PROVIDER",
    "MAS",
    "MAS-AGENT",
    "WORKFLOW",
    "TASK",
}

VALID_AUDIT_TYPES = {
    "RESOURCE_CREATED",
    "RESOURCE_UPDATED",
    "RESOURCE_DELETED",
    "RESOURCE_PURGED",
    "RESOURCE_PRUNED",
    "KNOWLEDGE_INGESTION",
    "KNOWLEDGE_QUERY",
    "MEMORY_OPERATION",
}


class AuditEventCreate(BaseModel):
    operation_id: str | None = None
    resource_type: str
    resource_identifier: str
    audit_type: str
    audit_resource_identifier: str
    audit_information: dict | None = None
    audit_extra_information: str | None = None
    created_by: UUID
    last_modified_by: UUID


class AuditEventRead(BaseModel):
    id: UUID
    operation_id: str | None = None
    resource_type: str
    resource_identifier: str
    audit_type: str
    audit_resource_identifier: str
    audit_information: dict | None = None
    audit_extra_information: str | None = None
    created_by: UUID
    created_on: datetime
    last_modified_by: UUID
    last_modified_on: datetime

    model_config = {"from_attributes": True}


# ── Memory ───────────────────────────────────────────────────────────────────


class MemoryCreate(BaseModel):
    key: str = Field(..., min_length=1, max_length=512)
    value: dict | str = Field(..., description="Memory content (dict or string)")
    tags: list[str] | None = None
    content_text: str | None = Field(
        None, description="Text for embedding; auto-generated from value if omitted"
    )
    embed: bool = Field(True, description="Generate vector embedding for semantic search")
    created_by: str = Field(..., description="Agent handle creating this memory")
    scope: str = Field("namespace", pattern="^(namespace|notebook)$")
    owner_handle: str | None = Field(
        None, description="Required for notebook scope — the owning agent handle"
    )


class MemoryBatchCreate(BaseModel):
    items: list[MemoryCreate] = Field(..., min_length=1, max_length=100)


class MemoryRead(BaseModel):
    id: UUID
    room_name: str
    key: str
    value: dict | str
    content_text: str | None = None
    created_by: str
    updated_by: str | None = None
    version: int
    tags: list[str] | None = None
    created_at: datetime
    updated_at: datetime
    scope: str = "namespace"
    owner_handle: str | None = None
    file_path: str | None = None

    model_config = {"from_attributes": True}


class MemorySearchRequest(BaseModel):
    query: str = Field(..., min_length=1)
    limit: int = Field(10, ge=1, le=100)
    tags_filter: list[str] | None = None
    min_similarity: float = Field(0.0, ge=0.0, le=1.0)


class MemorySearchResult(BaseModel):
    memory: MemoryRead
    similarity: float


class MemorySearchResponse(BaseModel):
    results: list[MemorySearchResult]
    total: int


class SubscriptionCreate(BaseModel):
    key_pattern: str = Field(..., min_length=1, description="Glob pattern for keys to watch")
    subscriber: str = Field(..., description="Agent handle subscribing")


class SubscriptionRead(BaseModel):
    id: UUID
    room_name: str
    subscriber: str
    key_pattern: str
    created_at: datetime

    model_config = {"from_attributes": True}
