from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

T = TypeVar("T", bound="SharedmemoryCreateOrUpdateAcceptedResponse")


@_attrs_define
class SharedmemoryCreateOrUpdateAcceptedResponse:
    """
    Attributes:
        message (str | Unset): Message provides additional information
        response_id (str | Unset): ID of the request, can be used for correlation in logs
        status (str | Unset): Status indicates the request was accepted for processing
    """

    message: str | Unset = UNSET
    response_id: str | Unset = UNSET
    status: str | Unset = UNSET
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        message = self.message

        response_id = self.response_id

        status = self.status

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update({})
        if message is not UNSET:
            field_dict["message"] = message
        if response_id is not UNSET:
            field_dict["response_id"] = response_id
        if status is not UNSET:
            field_dict["status"] = status

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        message = d.pop("message", UNSET)

        response_id = d.pop("response_id", UNSET)

        status = d.pop("status", UNSET)

        sharedmemory_create_or_update_accepted_response = cls(
            message=message,
            response_id=response_id,
            status=status,
        )

        sharedmemory_create_or_update_accepted_response.additional_properties = d
        return sharedmemory_create_or_update_accepted_response

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
