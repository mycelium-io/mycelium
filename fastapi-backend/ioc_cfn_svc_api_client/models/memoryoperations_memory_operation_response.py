from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, TypeVar

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

if TYPE_CHECKING:
    from ..models.memoryoperations_memory_operation_response_http_headers import (
        MemoryoperationsMemoryOperationResponseHttpHeaders,
    )
    from ..models.memoryoperations_memory_operation_response_http_response_body import (
        MemoryoperationsMemoryOperationResponseHttpResponseBody,
    )


T = TypeVar("T", bound="MemoryoperationsMemoryOperationResponse")


@_attrs_define
class MemoryoperationsMemoryOperationResponse:
    """
    Attributes:
        http_headers (MemoryoperationsMemoryOperationResponseHttpHeaders | Unset):
        http_response_body (MemoryoperationsMemoryOperationResponseHttpResponseBody | Unset):
        http_status (int | Unset):
    """

    http_headers: MemoryoperationsMemoryOperationResponseHttpHeaders | Unset = UNSET
    http_response_body: MemoryoperationsMemoryOperationResponseHttpResponseBody | Unset = UNSET
    http_status: int | Unset = UNSET
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        http_headers: dict[str, Any] | Unset = UNSET
        if not isinstance(self.http_headers, Unset):
            http_headers = self.http_headers.to_dict()

        http_response_body: dict[str, Any] | Unset = UNSET
        if not isinstance(self.http_response_body, Unset):
            http_response_body = self.http_response_body.to_dict()

        http_status = self.http_status

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update({})
        if http_headers is not UNSET:
            field_dict["http-headers"] = http_headers
        if http_response_body is not UNSET:
            field_dict["http-response-body"] = http_response_body
        if http_status is not UNSET:
            field_dict["http-status"] = http_status

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.memoryoperations_memory_operation_response_http_headers import (
            MemoryoperationsMemoryOperationResponseHttpHeaders,
        )
        from ..models.memoryoperations_memory_operation_response_http_response_body import (
            MemoryoperationsMemoryOperationResponseHttpResponseBody,
        )

        d = dict(src_dict)
        _http_headers = d.pop("http-headers", UNSET)
        http_headers: MemoryoperationsMemoryOperationResponseHttpHeaders | Unset
        if isinstance(_http_headers, Unset):
            http_headers = UNSET
        else:
            http_headers = MemoryoperationsMemoryOperationResponseHttpHeaders.from_dict(
                _http_headers
            )

        _http_response_body = d.pop("http-response-body", UNSET)
        http_response_body: MemoryoperationsMemoryOperationResponseHttpResponseBody | Unset
        if isinstance(_http_response_body, Unset):
            http_response_body = UNSET
        else:
            http_response_body = MemoryoperationsMemoryOperationResponseHttpResponseBody.from_dict(
                _http_response_body
            )

        http_status = d.pop("http-status", UNSET)

        memoryoperations_memory_operation_response = cls(
            http_headers=http_headers,
            http_response_body=http_response_body,
            http_status=http_status,
        )

        memoryoperations_memory_operation_response.additional_properties = d
        return memoryoperations_memory_operation_response

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
