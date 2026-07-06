from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, TypeVar

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

if TYPE_CHECKING:
    from ..models.sharedmemory_agent_vector_upsert_record import SharedmemoryAgentVectorUpsertRecord


T = TypeVar("T", bound="SharedmemoryAgentVectorUpsertRequest")


@_attrs_define
class SharedmemoryAgentVectorUpsertRequest:
    """
    Attributes:
        records (list[SharedmemoryAgentVectorUpsertRecord] | Unset):
        request_id (str | Unset):
    """

    records: list[SharedmemoryAgentVectorUpsertRecord] | Unset = UNSET
    request_id: str | Unset = UNSET
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        records: list[dict[str, Any]] | Unset = UNSET
        if not isinstance(self.records, Unset):
            records = []
            for records_item_data in self.records:
                records_item = records_item_data.to_dict()
                records.append(records_item)

        request_id = self.request_id

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update({})
        if records is not UNSET:
            field_dict["records"] = records
        if request_id is not UNSET:
            field_dict["request_id"] = request_id

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.sharedmemory_agent_vector_upsert_record import (
            SharedmemoryAgentVectorUpsertRecord,
        )

        d = dict(src_dict)
        _records = d.pop("records", UNSET)
        records: list[SharedmemoryAgentVectorUpsertRecord] | Unset = UNSET
        if _records is not UNSET:
            records = []
            for records_item_data in _records:
                records_item = SharedmemoryAgentVectorUpsertRecord.from_dict(records_item_data)

                records.append(records_item)

        request_id = d.pop("request_id", UNSET)

        sharedmemory_agent_vector_upsert_request = cls(
            records=records,
            request_id=request_id,
        )

        sharedmemory_agent_vector_upsert_request.additional_properties = d
        return sharedmemory_agent_vector_upsert_request

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
