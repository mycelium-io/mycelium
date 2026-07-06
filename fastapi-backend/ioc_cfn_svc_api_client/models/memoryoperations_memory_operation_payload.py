from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, TypeVar

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

if TYPE_CHECKING:
    from ..models.memoryoperations_memory_operation_payload_http_headers import (
        MemoryoperationsMemoryOperationPayloadHttpHeaders,
    )
    from ..models.memoryoperations_memory_operation_payload_http_request_body import (
        MemoryoperationsMemoryOperationPayloadHttpRequestBody,
    )


T = TypeVar("T", bound="MemoryoperationsMemoryOperationPayload")


@_attrs_define
class MemoryoperationsMemoryOperationPayload:
    """
    Attributes:
        http_headers (MemoryoperationsMemoryOperationPayloadHttpHeaders | Unset): Custom headers
        http_request_body (MemoryoperationsMemoryOperationPayloadHttpRequestBody | Unset): JSON payload
        http_request_type (str | Unset): POST, PUT, GET, DELETE, etc.
        http_url (str | Unset): URL with query parameters (URL encoded)
    """

    http_headers: MemoryoperationsMemoryOperationPayloadHttpHeaders | Unset = UNSET
    http_request_body: MemoryoperationsMemoryOperationPayloadHttpRequestBody | Unset = UNSET
    http_request_type: str | Unset = UNSET
    http_url: str | Unset = UNSET
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        http_headers: dict[str, Any] | Unset = UNSET
        if not isinstance(self.http_headers, Unset):
            http_headers = self.http_headers.to_dict()

        http_request_body: dict[str, Any] | Unset = UNSET
        if not isinstance(self.http_request_body, Unset):
            http_request_body = self.http_request_body.to_dict()

        http_request_type = self.http_request_type

        http_url = self.http_url

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update({})
        if http_headers is not UNSET:
            field_dict["http-headers"] = http_headers
        if http_request_body is not UNSET:
            field_dict["http-request-body"] = http_request_body
        if http_request_type is not UNSET:
            field_dict["http-request-type"] = http_request_type
        if http_url is not UNSET:
            field_dict["http-url"] = http_url

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.memoryoperations_memory_operation_payload_http_headers import (
            MemoryoperationsMemoryOperationPayloadHttpHeaders,
        )
        from ..models.memoryoperations_memory_operation_payload_http_request_body import (
            MemoryoperationsMemoryOperationPayloadHttpRequestBody,
        )

        d = dict(src_dict)
        _http_headers = d.pop("http-headers", UNSET)
        http_headers: MemoryoperationsMemoryOperationPayloadHttpHeaders | Unset
        if isinstance(_http_headers, Unset):
            http_headers = UNSET
        else:
            http_headers = MemoryoperationsMemoryOperationPayloadHttpHeaders.from_dict(
                _http_headers
            )

        _http_request_body = d.pop("http-request-body", UNSET)
        http_request_body: MemoryoperationsMemoryOperationPayloadHttpRequestBody | Unset
        if isinstance(_http_request_body, Unset):
            http_request_body = UNSET
        else:
            http_request_body = MemoryoperationsMemoryOperationPayloadHttpRequestBody.from_dict(
                _http_request_body
            )

        http_request_type = d.pop("http-request-type", UNSET)

        http_url = d.pop("http-url", UNSET)

        memoryoperations_memory_operation_payload = cls(
            http_headers=http_headers,
            http_request_body=http_request_body,
            http_request_type=http_request_type,
            http_url=http_url,
        )

        memoryoperations_memory_operation_payload.additional_properties = d
        return memoryoperations_memory_operation_payload

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
