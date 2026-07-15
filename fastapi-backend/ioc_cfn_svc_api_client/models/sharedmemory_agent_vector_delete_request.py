from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, TypeVar

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

if TYPE_CHECKING:
    from ..models.sharedmemory_vector_delete_metadata_filter import (
        SharedmemoryVectorDeleteMetadataFilter,
    )


T = TypeVar("T", bound="SharedmemoryAgentVectorDeleteRequest")


@_attrs_define
class SharedmemoryAgentVectorDeleteRequest:
    """
    Attributes:
        filters (SharedmemoryVectorDeleteMetadataFilter | Unset):
        id (str | Unset):
        request_id (str | Unset):
    """

    filters: SharedmemoryVectorDeleteMetadataFilter | Unset = UNSET
    id: str | Unset = UNSET
    request_id: str | Unset = UNSET
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        filters: dict[str, Any] | Unset = UNSET
        if not isinstance(self.filters, Unset):
            filters = self.filters.to_dict()

        id = self.id

        request_id = self.request_id

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update({})
        if filters is not UNSET:
            field_dict["filters"] = filters
        if id is not UNSET:
            field_dict["id"] = id
        if request_id is not UNSET:
            field_dict["request_id"] = request_id

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.sharedmemory_vector_delete_metadata_filter import (
            SharedmemoryVectorDeleteMetadataFilter,
        )

        d = dict(src_dict)
        _filters = d.pop("filters", UNSET)
        filters: SharedmemoryVectorDeleteMetadataFilter | Unset
        if isinstance(_filters, Unset):
            filters = UNSET
        else:
            filters = SharedmemoryVectorDeleteMetadataFilter.from_dict(_filters)

        id = d.pop("id", UNSET)

        request_id = d.pop("request_id", UNSET)

        sharedmemory_agent_vector_delete_request = cls(
            filters=filters,
            id=id,
            request_id=request_id,
        )

        sharedmemory_agent_vector_delete_request.additional_properties = d
        return sharedmemory_agent_vector_delete_request

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
