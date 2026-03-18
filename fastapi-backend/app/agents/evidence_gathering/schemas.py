"""Evidence gathering request/response schemas (ported from ioc-cfn-cognitive-agents)."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

QueryType = Literal["Semantic Graph Traversal"]


class Header(BaseModel):
    workspace_id: str = Field(..., description="Mandatory workspace identifier")
    mas_id: str = Field(..., description="Mandatory MAS identifier")
    agent_id: str | None = Field(None, description="Optional agent identifier")


class QueryMetadata(BaseModel):
    query_type: QueryType | None = Field(default="Semantic Graph Traversal")


class RequestPayload(BaseModel):
    intent: str
    metadata: QueryMetadata | None = Field(default_factory=QueryMetadata)
    additional_context: list[dict[str, Any]] | None = Field(default_factory=list)
    records: list[dict[str, Any]] | None = Field(default_factory=list)


class ReasonerCognitionRequest(BaseModel):
    header: Header
    request_id: str
    payload: RequestPayload


class KnowledgeRecord(BaseModel):
    id: str = Field(default="auto")
    type: Literal["json"] = "json"
    content: dict[str, Any]


class ErrorDetail(BaseModel):
    message: str
    detail: dict[str, Any] | None = None


class ReasonerCognitionResponse(BaseModel):
    header: Header
    response_id: str
    error: ErrorDetail | None = None
    records: list[KnowledgeRecord] = Field(default_factory=list)
    metadata: dict[str, Any] | None = Field(default_factory=dict)
