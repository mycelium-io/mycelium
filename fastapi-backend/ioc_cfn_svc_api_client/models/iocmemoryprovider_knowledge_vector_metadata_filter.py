from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

T = TypeVar("T", bound="IocmemoryproviderKnowledgeVectorMetadataFilter")


@_attrs_define
class IocmemoryproviderKnowledgeVectorMetadataFilter:
    """
    Attributes:
        chunk_index (int | Unset):
        data_source (str | Unset):
        doc_index (int | Unset):
        recorded_at_from (str | Unset):
        recorded_at_to (str | Unset):
    """

    chunk_index: int | Unset = UNSET
    data_source: str | Unset = UNSET
    doc_index: int | Unset = UNSET
    recorded_at_from: str | Unset = UNSET
    recorded_at_to: str | Unset = UNSET
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        chunk_index = self.chunk_index

        data_source = self.data_source

        doc_index = self.doc_index

        recorded_at_from = self.recorded_at_from

        recorded_at_to = self.recorded_at_to

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update({})
        if chunk_index is not UNSET:
            field_dict["chunk_index"] = chunk_index
        if data_source is not UNSET:
            field_dict["data_source"] = data_source
        if doc_index is not UNSET:
            field_dict["doc_index"] = doc_index
        if recorded_at_from is not UNSET:
            field_dict["recorded_at_from"] = recorded_at_from
        if recorded_at_to is not UNSET:
            field_dict["recorded_at_to"] = recorded_at_to

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        chunk_index = d.pop("chunk_index", UNSET)

        data_source = d.pop("data_source", UNSET)

        doc_index = d.pop("doc_index", UNSET)

        recorded_at_from = d.pop("recorded_at_from", UNSET)

        recorded_at_to = d.pop("recorded_at_to", UNSET)

        iocmemoryprovider_knowledge_vector_metadata_filter = cls(
            chunk_index=chunk_index,
            data_source=data_source,
            doc_index=doc_index,
            recorded_at_from=recorded_at_from,
            recorded_at_to=recorded_at_to,
        )

        iocmemoryprovider_knowledge_vector_metadata_filter.additional_properties = d
        return iocmemoryprovider_knowledge_vector_metadata_filter

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
