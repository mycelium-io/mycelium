from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, TypeVar, cast

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..models.cognitionagents_request_type import CognitionagentsRequestType
from ..types import UNSET, Unset

if TYPE_CHECKING:
    from ..models.common_header import CommonHeader


T = TypeVar("T", bound="CognitionagentsSharedMemoryVectorsRequest")


@_attrs_define
class CognitionagentsSharedMemoryVectorsRequest:
    """
    Attributes:
        header (CommonHeader | Unset):
        request_body (list[int] | Unset):
        request_type (CognitionagentsRequestType | Unset):
    """

    header: CommonHeader | Unset = UNSET
    request_body: list[int] | Unset = UNSET
    request_type: CognitionagentsRequestType | Unset = UNSET
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        header: dict[str, Any] | Unset = UNSET
        if not isinstance(self.header, Unset):
            header = self.header.to_dict()

        request_body: list[int] | Unset = UNSET
        if not isinstance(self.request_body, Unset):
            request_body = self.request_body

        request_type: str | Unset = UNSET
        if not isinstance(self.request_type, Unset):
            request_type = self.request_type.value

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update({})
        if header is not UNSET:
            field_dict["header"] = header
        if request_body is not UNSET:
            field_dict["request_body"] = request_body
        if request_type is not UNSET:
            field_dict["request_type"] = request_type

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.common_header import CommonHeader

        d = dict(src_dict)
        _header = d.pop("header", UNSET)
        header: CommonHeader | Unset
        if isinstance(_header, Unset):
            header = UNSET
        else:
            header = CommonHeader.from_dict(_header)

        request_body = cast(list[int], d.pop("request_body", UNSET))

        _request_type = d.pop("request_type", UNSET)
        request_type: CognitionagentsRequestType | Unset
        if isinstance(_request_type, Unset):
            request_type = UNSET
        else:
            request_type = CognitionagentsRequestType(_request_type)

        cognitionagents_shared_memory_vectors_request = cls(
            header=header,
            request_body=request_body,
            request_type=request_type,
        )

        cognitionagents_shared_memory_vectors_request.additional_properties = d
        return cognitionagents_shared_memory_vectors_request

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
