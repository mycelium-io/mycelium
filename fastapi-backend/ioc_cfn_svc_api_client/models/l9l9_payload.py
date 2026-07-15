from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, TypeVar

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

if TYPE_CHECKING:
    from ..models.l9l9_payload_data import L9L9PayloadData


T = TypeVar("T", bound="L9L9Payload")


@_attrs_define
class L9L9Payload:
    """
    Attributes:
        data (L9L9PayloadData | Unset):
        type_ (str | Unset): Type corresponds to the JSON schema field "type".
    """

    data: L9L9PayloadData | Unset = UNSET
    type_: str | Unset = UNSET
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        data: dict[str, Any] | Unset = UNSET
        if not isinstance(self.data, Unset):
            data = self.data.to_dict()

        type_ = self.type_

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update({})
        if data is not UNSET:
            field_dict["data"] = data
        if type_ is not UNSET:
            field_dict["type"] = type_

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.l9l9_payload_data import L9L9PayloadData

        d = dict(src_dict)
        _data = d.pop("data", UNSET)
        data: L9L9PayloadData | Unset
        if isinstance(_data, Unset):
            data = UNSET
        else:
            data = L9L9PayloadData.from_dict(_data)

        type_ = d.pop("type", UNSET)

        l9l9_payload = cls(
            data=data,
            type_=type_,
        )

        l9l9_payload.additional_properties = d
        return l9l9_payload

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
