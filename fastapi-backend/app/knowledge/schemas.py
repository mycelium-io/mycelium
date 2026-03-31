# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Julia Valenti

"""Knowledge graph API schemas — ported from ioc-knowledge-memory-svc."""

from enum import Enum
from typing import Annotated, Any, Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class ResponseStatus(str, Enum):
    SUCCESS = "success"
    FAILURE = "failure"
    VALIDATION_ERROR = "validation error"
    NOT_FOUND = "not found"


class EmbeddingConfig(BaseModel):
    name: str = Field(..., description="Embedding model name")
    data: list[float] = Field(default_factory=list)


class Concept(BaseModel):
    id: str
    name: str
    description: str | None = None
    attributes: dict[str, Any] | None = Field(default_factory=dict)
    embeddings: EmbeddingConfig | None = None
    tags: list[str] | None = Field(default_factory=list)


class Relation(BaseModel):
    id: str
    relation: str
    node_ids: Annotated[list[str], Field(..., min_length=2)]
    attributes: dict[str, Any] | None = Field(default_factory=dict)
    embeddings: EmbeddingConfig | None = None

    @field_validator("node_ids", mode="after")
    @classmethod
    def validate_node_count(cls, v: list[str]) -> list[str]:
        if len(v) < 2:
            raise ValueError("A relation must connect at least 2 nodes")
        return v


# ── Store ──────────────────────────────────────────────────────────────────────


class KnowledgeGraphStoreRequest(BaseModel):
    request_id: str = Field(default_factory=lambda: str(uuid4()))
    records: dict[Literal["concepts", "relations"], Any] | None = None
    memory_type: Literal["Semantic", "Procedural", "Episodic"] | None = None
    mas_id: str | None = Field(default=None, min_length=1)
    wksp_id: str | None = Field(default=None, min_length=1)
    force_replace: bool = False

    @model_validator(mode="after")
    def require_mas_or_wksp(self) -> "KnowledgeGraphStoreRequest":
        if not self.mas_id and not self.wksp_id:
            raise ValueError("Either mas_id or wksp_id must be provided")
        return self

    @model_validator(mode="after")
    def validate_records(self) -> "KnowledgeGraphStoreRequest":
        if self.records is None:
            return self
        if not isinstance(self.records.get("concepts"), list):
            raise ValueError("'concepts' must be a list")
        if not isinstance(self.records.get("relations"), list):
            raise ValueError("'relations' must be a list")
        concept_ids = {c.get("id") for c in self.records.get("concepts", [])}
        for rel in self.records.get("relations", []):
            if not isinstance(rel, dict):
                continue
            for nid in rel.get("node_ids", []):
                if nid not in concept_ids:
                    raise ValueError(
                        f"Relation '{rel.get('id', 'unknown')}' references unknown node '{nid}'"
                    )
        return self


class KnowledgeGraphStoreResponse(BaseModel):
    model_config = ConfigDict(exclude_none=True)
    request_id: str | None = None
    status: ResponseStatus
    message: str | None = None

    def model_dump(self, **kwargs) -> dict[str, Any]:
        data = super().model_dump(**kwargs)
        if self.request_id is None:
            data.pop("request_id", None)
        return data


# ── Delete ─────────────────────────────────────────────────────────────────────


class KnowledgeGraphDeleteRequest(BaseModel):
    request_id: str = Field(default_factory=lambda: str(uuid4()))
    records: dict[Literal["concepts"], Any] | None = None
    mas_id: str | None = Field(default=None, min_length=1)
    wksp_id: str | None = Field(default=None, min_length=1)

    @model_validator(mode="after")
    def require_mas_or_wksp(self) -> "KnowledgeGraphDeleteRequest":
        if not self.mas_id and not self.wksp_id:
            raise ValueError("Either mas_id or wksp_id must be provided")
        return self


class KnowledgeGraphDeleteResponse(BaseModel):
    model_config = ConfigDict(exclude_none=True)
    request_id: str | None = None
    status: ResponseStatus
    message: str | None = None

    def model_dump(self, **kwargs) -> dict[str, Any]:
        data = super().model_dump(**kwargs)
        if self.request_id is None:
            data.pop("request_id", None)
        return data


# ── Query ──────────────────────────────────────────────────────────────────────

QUERY_TYPE_NEIGHBOUR = "neighbour"
QUERY_TYPE_PATH = "path"
QUERY_TYPE_CONCEPT = "concept"


class KnowledgeGraphQueryCriteria(BaseModel):
    depth: int | None = None
    use_direction: bool | None = True
    query_type: str = Field(default=QUERY_TYPE_NEIGHBOUR)


class KnowledgeGraphQueryRequest(BaseModel):
    request_id: str = Field(default_factory=lambda: str(uuid4()))
    records: dict[Literal["concepts"], Any] = Field(...)
    memory_type: str | None = Field(default=None, min_length=1)
    mas_id: str | None = Field(default=None, min_length=1)
    wksp_id: str | None = Field(default=None, min_length=1)
    query_criteria: KnowledgeGraphQueryCriteria | None = Field(
        default_factory=KnowledgeGraphQueryCriteria
    )

    @model_validator(mode="after")
    def require_mas_or_wksp(self) -> "KnowledgeGraphQueryRequest":
        if not self.mas_id and not self.wksp_id:
            raise ValueError("Either mas_id or wksp_id must be provided")
        return self

    @model_validator(mode="after")
    def validate_concept_count(self) -> "KnowledgeGraphQueryRequest":
        concepts = (self.records or {}).get("concepts", [])
        if not isinstance(concepts, list):
            raise ValueError("concepts must be a list")
        qt = self.query_criteria.query_type if self.query_criteria else QUERY_TYPE_NEIGHBOUR
        if qt == QUERY_TYPE_PATH and len(concepts) != 2:
            raise ValueError("Path queries require exactly 2 concepts")
        if qt in (QUERY_TYPE_NEIGHBOUR, QUERY_TYPE_CONCEPT) and len(concepts) != 1:
            raise ValueError(f"{qt} queries require exactly 1 concept")
        return self


class KnowledgeGraphQueryResponseRecord(BaseModel):
    relationships: list[Relation] = Field(default_factory=list)
    concepts: list[Concept] = Field(default_factory=list)


class KnowledgeGraphQueryResponse(BaseModel):
    model_config = ConfigDict(exclude_none=True)
    request_id: str | None = None
    status: ResponseStatus
    message: str | None = None
    records: list[KnowledgeGraphQueryResponseRecord] | None = None

    def model_dump(self, **kwargs) -> dict[str, Any]:
        data = super().model_dump(**kwargs)
        if not self.records:
            data.pop("records", None)
        if self.request_id is None:
            data.pop("request_id", None)
        return data
