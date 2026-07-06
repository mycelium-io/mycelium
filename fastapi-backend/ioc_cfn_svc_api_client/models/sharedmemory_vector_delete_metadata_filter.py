from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, TypeVar

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

if TYPE_CHECKING:
    from ..models.sharedmemory_vector_delete_metadata_filter_extra_filters import (
        SharedmemoryVectorDeleteMetadataFilterExtraFilters,
    )


T = TypeVar("T", bound="SharedmemoryVectorDeleteMetadataFilter")


@_attrs_define
class SharedmemoryVectorDeleteMetadataFilter:
    """
    Attributes:
        chunk_index (int | Unset):
        data_source (str | Unset):
        doc_index (int | Unset):
        extra_filters (SharedmemoryVectorDeleteMetadataFilterExtraFilters | Unset):
        recorded_at_from (str | Unset):
        recorded_at_to (str | Unset):
    """

    chunk_index: int | Unset = UNSET
    data_source: str | Unset = UNSET
    doc_index: int | Unset = UNSET
    extra_filters: SharedmemoryVectorDeleteMetadataFilterExtraFilters | Unset = UNSET
    recorded_at_from: str | Unset = UNSET
    recorded_at_to: str | Unset = UNSET
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        chunk_index = self.chunk_index

        data_source = self.data_source

        doc_index = self.doc_index

        extra_filters: dict[str, Any] | Unset = UNSET
        if not isinstance(self.extra_filters, Unset):
            extra_filters = self.extra_filters.to_dict()

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
        if extra_filters is not UNSET:
            field_dict["extra_filters"] = extra_filters
        if recorded_at_from is not UNSET:
            field_dict["recorded_at_from"] = recorded_at_from
        if recorded_at_to is not UNSET:
            field_dict["recorded_at_to"] = recorded_at_to

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.sharedmemory_vector_delete_metadata_filter_extra_filters import (
            SharedmemoryVectorDeleteMetadataFilterExtraFilters,
        )

        d = dict(src_dict)
        chunk_index = d.pop("chunk_index", UNSET)

        data_source = d.pop("data_source", UNSET)

        doc_index = d.pop("doc_index", UNSET)

        _extra_filters = d.pop("extra_filters", UNSET)
        extra_filters: SharedmemoryVectorDeleteMetadataFilterExtraFilters | Unset
        if isinstance(_extra_filters, Unset):
            extra_filters = UNSET
        else:
            extra_filters = SharedmemoryVectorDeleteMetadataFilterExtraFilters.from_dict(
                _extra_filters
            )

        recorded_at_from = d.pop("recorded_at_from", UNSET)

        recorded_at_to = d.pop("recorded_at_to", UNSET)

        sharedmemory_vector_delete_metadata_filter = cls(
            chunk_index=chunk_index,
            data_source=data_source,
            doc_index=doc_index,
            extra_filters=extra_filters,
            recorded_at_from=recorded_at_from,
            recorded_at_to=recorded_at_to,
        )

        sharedmemory_vector_delete_metadata_filter.additional_properties = d
        return sharedmemory_vector_delete_metadata_filter

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
