from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, TypeVar

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

if TYPE_CHECKING:
    from ..models.sharedmemory_agent_vector_upsert_record_metadata import (
        SharedmemoryAgentVectorUpsertRecordMetadata,
    )
    from ..models.sharedmemory_vector_embedding_payload import SharedmemoryVectorEmbeddingPayload


T = TypeVar("T", bound="SharedmemoryAgentVectorUpsertRecord")


@_attrs_define
class SharedmemoryAgentVectorUpsertRecord:
    """
    Attributes:
        content (str | Unset):
        embedding (SharedmemoryVectorEmbeddingPayload | Unset):
        id (str | Unset):
        metadata (SharedmemoryAgentVectorUpsertRecordMetadata | Unset):
    """

    content: str | Unset = UNSET
    embedding: SharedmemoryVectorEmbeddingPayload | Unset = UNSET
    id: str | Unset = UNSET
    metadata: SharedmemoryAgentVectorUpsertRecordMetadata | Unset = UNSET
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        content = self.content

        embedding: dict[str, Any] | Unset = UNSET
        if not isinstance(self.embedding, Unset):
            embedding = self.embedding.to_dict()

        id = self.id

        metadata: dict[str, Any] | Unset = UNSET
        if not isinstance(self.metadata, Unset):
            metadata = self.metadata.to_dict()

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update({})
        if content is not UNSET:
            field_dict["content"] = content
        if embedding is not UNSET:
            field_dict["embedding"] = embedding
        if id is not UNSET:
            field_dict["id"] = id
        if metadata is not UNSET:
            field_dict["metadata"] = metadata

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.sharedmemory_agent_vector_upsert_record_metadata import (
            SharedmemoryAgentVectorUpsertRecordMetadata,
        )
        from ..models.sharedmemory_vector_embedding_payload import (
            SharedmemoryVectorEmbeddingPayload,
        )

        d = dict(src_dict)
        content = d.pop("content", UNSET)

        _embedding = d.pop("embedding", UNSET)
        embedding: SharedmemoryVectorEmbeddingPayload | Unset
        if isinstance(_embedding, Unset):
            embedding = UNSET
        else:
            embedding = SharedmemoryVectorEmbeddingPayload.from_dict(_embedding)

        id = d.pop("id", UNSET)

        _metadata = d.pop("metadata", UNSET)
        metadata: SharedmemoryAgentVectorUpsertRecordMetadata | Unset
        if isinstance(_metadata, Unset):
            metadata = UNSET
        else:
            metadata = SharedmemoryAgentVectorUpsertRecordMetadata.from_dict(_metadata)

        sharedmemory_agent_vector_upsert_record = cls(
            content=content,
            embedding=embedding,
            id=id,
            metadata=metadata,
        )

        sharedmemory_agent_vector_upsert_record.additional_properties = d
        return sharedmemory_agent_vector_upsert_record

    @property
    def additional_keys(self) -> list[str]:
        return list(self.additional_properties.keys())

    def __getitem__(self, key: str) -> Any:
        return self.additional_properties[key]

    def __setitem__(self, key: str, value: Any) -> None:
        self.additional_properties[key] = value

    def __delitem__(self, key: str) -> None:
        del self.additional_properties[key]

    def __contains__(self, key: str) -> bool:
        return key in self.additional_properties
