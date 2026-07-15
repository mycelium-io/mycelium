from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, TypeVar

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

if TYPE_CHECKING:
    from ..models.cognitionagentclient_extraction_payload import (
        CognitionagentclientExtractionPayload,
    )
    from ..models.sharedmemory_header import SharedmemoryHeader


T = TypeVar("T", bound="SharedmemoryCreateOrUpdateRequest")


@_attrs_define
class SharedmemoryCreateOrUpdateRequest:
    """
    Attributes:
        header (SharedmemoryHeader | Unset):
        payload (CognitionagentclientExtractionPayload | Unset):
        request_id (str | Unset): ID of the request, optional. If not provided, a random UUID is used to represent the
            request
    """

    header: SharedmemoryHeader | Unset = UNSET
    payload: CognitionagentclientExtractionPayload | Unset = UNSET
    request_id: str | Unset = UNSET
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        header: dict[str, Any] | Unset = UNSET
        if not isinstance(self.header, Unset):
            header = self.header.to_dict()

        payload: dict[str, Any] | Unset = UNSET
        if not isinstance(self.payload, Unset):
            payload = self.payload.to_dict()

        request_id = self.request_id

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update({})
        if header is not UNSET:
            field_dict["header"] = header
        if payload is not UNSET:
            field_dict["payload"] = payload
        if request_id is not UNSET:
            field_dict["request_id"] = request_id

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.cognitionagentclient_extraction_payload import (
            CognitionagentclientExtractionPayload,
        )
        from ..models.sharedmemory_header import SharedmemoryHeader

        d = dict(src_dict)
        _header = d.pop("header", UNSET)
        header: SharedmemoryHeader | Unset
        if isinstance(_header, Unset):
            header = UNSET
        else:
            header = SharedmemoryHeader.from_dict(_header)

        _payload = d.pop("payload", UNSET)
        payload: CognitionagentclientExtractionPayload | Unset
        if isinstance(_payload, Unset):
            payload = UNSET
        else:
            payload = CognitionagentclientExtractionPayload.from_dict(_payload)

        request_id = d.pop("request_id", UNSET)

        sharedmemory_create_or_update_request = cls(
            header=header,
            payload=payload,
            request_id=request_id,
        )

        sharedmemory_create_or_update_request.additional_properties = d
        return sharedmemory_create_or_update_request

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
