from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, TypeVar, cast

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

if TYPE_CHECKING:
    from ..models.iocmemoryprovider_knowledge_vector_metadata_filter import (
        IocmemoryproviderKnowledgeVectorMetadataFilter,
    )


T = TypeVar("T", bound="SharedmemoryVectorSimilaritySearchPayload")


@_attrs_define
class SharedmemoryVectorSimilaritySearchPayload:
    """
    Attributes:
        embedded_text (str | Unset):
        embedding_vector (list[float] | Unset):
        filters (IocmemoryproviderKnowledgeVectorMetadataFilter | Unset):
        search_metrics (str | Unset):
        top_k (int | Unset):
    """

    embedded_text: str | Unset = UNSET
    embedding_vector: list[float] | Unset = UNSET
    filters: IocmemoryproviderKnowledgeVectorMetadataFilter | Unset = UNSET
    search_metrics: str | Unset = UNSET
    top_k: int | Unset = UNSET
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        embedded_text = self.embedded_text

        embedding_vector: list[float] | Unset = UNSET
        if not isinstance(self.embedding_vector, Unset):
            embedding_vector = self.embedding_vector

        filters: dict[str, Any] | Unset = UNSET
        if not isinstance(self.filters, Unset):
            filters = self.filters.to_dict()

        search_metrics = self.search_metrics

        top_k = self.top_k

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update({})
        if embedded_text is not UNSET:
            field_dict["embedded_text"] = embedded_text
        if embedding_vector is not UNSET:
            field_dict["embedding_vector"] = embedding_vector
        if filters is not UNSET:
            field_dict["filters"] = filters
        if search_metrics is not UNSET:
            field_dict["search_metrics"] = search_metrics
        if top_k is not UNSET:
            field_dict["top_k"] = top_k

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.iocmemoryprovider_knowledge_vector_metadata_filter import (
            IocmemoryproviderKnowledgeVectorMetadataFilter,
        )

        d = dict(src_dict)
        embedded_text = d.pop("embedded_text", UNSET)

        embedding_vector = cast(list[float], d.pop("embedding_vector", UNSET))

        _filters = d.pop("filters", UNSET)
        filters: IocmemoryproviderKnowledgeVectorMetadataFilter | Unset
        if isinstance(_filters, Unset):
            filters = UNSET
        else:
            filters = IocmemoryproviderKnowledgeVectorMetadataFilter.from_dict(_filters)

        search_metrics = d.pop("search_metrics", UNSET)

        top_k = d.pop("top_k", UNSET)

        sharedmemory_vector_similarity_search_payload = cls(
            embedded_text=embedded_text,
            embedding_vector=embedding_vector,
            filters=filters,
            search_metrics=search_metrics,
            top_k=top_k,
        )

        sharedmemory_vector_similarity_search_payload.additional_properties = d
        return sharedmemory_vector_similarity_search_payload

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
