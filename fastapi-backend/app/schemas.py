"""
Minimal schemas for Mycelium's core models.
"""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field

# ── Workspace ─────────────────────────────────────────────────────────────────

class WorkspaceCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)


class WorkspaceRead(BaseModel):
    id: UUID
    name: str
    created_at: datetime

    model_config = {"from_attributes": True}


# ── MAS ───────────────────────────────────────────────────────────────────────

class MASCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    config: dict | None = None


class MASRead(BaseModel):
    id: UUID
    workspace_id: UUID
    name: str
    config: dict | None = None
    created_at: datetime

    model_config = {"from_attributes": True}


# ── Agent ─────────────────────────────────────────────────────────────────────

class AgentCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    memory_provider_url: str | None = None
    memory_config: dict | None = None


class AgentUpdate(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=255)
    memory_provider_url: str | None = None
    memory_config: dict | None = None


class AgentRead(BaseModel):
    id: UUID
    mas_id: UUID
    name: str
    memory_provider_url: str | None = None
    memory_config: dict | None = None
    created_at: datetime

    model_config = {"from_attributes": True}


# ── Room ──────────────────────────────────────────────────────────────────────

class RoomCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    description: str | None = Field(None, max_length=500)
    is_public: bool = True


class RoomRead(BaseModel):
    id: int
    name: str
    description: str | None = None
    is_public: bool
    created_at: datetime
    coordination_state: str = "idle"

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
    joined_at: datetime
    last_seen: datetime | None = None

    model_config = {"from_attributes": True}


class SessionListResponse(BaseModel):
    sessions: list[SessionRead]
    total: int


# ── AuditEvent ────────────────────────────────────────────────────────────────

VALID_RESOURCE_TYPES = {
    "COGNITIVE_ENGINE", "POLICY_ENFORCER", "MEMORY_PROVIDER",
    "MAS", "MAS-AGENT", "WORKFLOW", "TASK",
}

VALID_AUDIT_TYPES = {
    "RESOURCE_CREATED", "RESOURCE_UPDATED", "RESOURCE_DELETED",
    "RESOURCE_PURGED", "RESOURCE_PRUNED",
    "KNOWLEDGE_INGESTION", "KNOWLEDGE_QUERY", "MEMORY_OPERATION",
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
