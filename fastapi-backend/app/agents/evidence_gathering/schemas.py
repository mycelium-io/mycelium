"""Evidence gathering request/response schemas (ported from ioc-cfn-cognitive-agents)."""
from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field

QueryType = Literal["Semantic Graph Traversal"]


class Header(BaseModel):
    workspace_id: str = Field(..., description="Mandatory workspace identifier")
    mas_id: str = Field(..., description="Mandatory MAS identifier")
    agent_id: Optional[str] = Field(None, description="Optional agent identifier")


class QueryMetadata(BaseModel):
    query_type: Optional[QueryType] = Field(default="Semantic Graph Traversal")


class RequestPayload(BaseModel):
    intent: str
    metadata: Optional[QueryMetadata] = Field(default_factory=QueryMetadata)
    additional_context: Optional[List[Dict[str, Any]]] = Field(default_factory=list)
    records: Optional[List[Dict[str, Any]]] = Field(default_factory=list)


class ReasonerCognitionRequest(BaseModel):
    header: Header
    request_id: str
    payload: RequestPayload


class KnowledgeRecord(BaseModel):
    id: str = Field(default="auto")
    type: Literal["json"] = "json"
    content: Dict[str, Any]


class ErrorDetail(BaseModel):
    message: str
    detail: Optional[Dict[str, Any]] = None


class ReasonerCognitionResponse(BaseModel):
    header: Header
    response_id: str
    error: Optional[ErrorDetail] = None
    records: List[KnowledgeRecord] = Field(default_factory=list)
    metadata: Optional[Dict[str, Any]] = Field(default_factory=dict)
