from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, TypeVar

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

if TYPE_CHECKING:
    from ..models.l9l9_header import L9L9Header
    from ..models.l9l9_payload import L9L9Payload


T = TypeVar("T", bound="L9L9")


@_attrs_define
class L9L9:
    """
    Attributes:
        header (L9L9Header | Unset):
        payload (L9L9Payload | Unset):
    """

    header: L9L9Header | Unset = UNSET
    payload: L9L9Payload | Unset = UNSET
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        header: dict[str, Any] | Unset = UNSET
        if not isinstance(self.header, Unset):
            header = self.header.to_dict()

        payload: dict[str, Any] | Unset = UNSET
        if not isinstance(self.payload, Unset):
            payload = self.payload.to_dict()

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update({})
        if header is not UNSET:
            field_dict["header"] = header
        if payload is not UNSET:
            field_dict["payload"] = payload

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.l9l9_header import L9L9Header
        from ..models.l9l9_payload import L9L9Payload

        d = dict(src_dict)
        _header = d.pop("header", UNSET)
        header: L9L9Header | Unset
        if isinstance(_header, Unset):
            header = UNSET
        else:
            header = L9L9Header.from_dict(_header)

        _payload = d.pop("payload", UNSET)
        payload: L9L9Payload | Unset
        if isinstance(_payload, Unset):
            payload = UNSET
        else:
            payload = L9L9Payload.from_dict(_payload)

        l9l9 = cls(
            header=header,
            payload=payload,
        )

        l9l9.additional_properties = d
        return l9l9

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
