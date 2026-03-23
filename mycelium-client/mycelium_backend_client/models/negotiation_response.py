from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, TypeVar

from attrs import define as _attrs_define
from attrs import field as _attrs_field

if TYPE_CHECKING:
    from ..models.cfn_header import CfnHeader


T = TypeVar("T", bound="NegotiationResponse")


@_attrs_define
class NegotiationResponse:
    """
    Attributes:
        header (CfnHeader):
        response_id (str):
    """

    header: CfnHeader
    response_id: str
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        header = self.header.to_dict()

        response_id = self.response_id

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "header": header,
                "response_id": response_id,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.cfn_header import CfnHeader

        d = dict(src_dict)
        header = CfnHeader.from_dict(d.pop("header"))

        response_id = d.pop("response_id")

        negotiation_response = cls(
            header=header,
            response_id=response_id,
        )

        negotiation_response.additional_properties = d
        return negotiation_response

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
