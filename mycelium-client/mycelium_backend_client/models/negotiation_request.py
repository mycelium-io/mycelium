from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, TypeVar

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

if TYPE_CHECKING:
    from ..models.cfn_header import CfnHeader
    from ..models.negotiation_request_payload import NegotiationRequestPayload


T = TypeVar("T", bound="NegotiationRequest")


@_attrs_define
class NegotiationRequest:
    """
    Attributes:
        header (CfnHeader):
        request_id (str | Unset):
        payload (NegotiationRequestPayload | Unset):
    """

    header: CfnHeader
    request_id: str | Unset = UNSET
    payload: NegotiationRequestPayload | Unset = UNSET
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        header = self.header.to_dict()

        request_id = self.request_id

        payload: dict[str, Any] | Unset = UNSET
        if not isinstance(self.payload, Unset):
            payload = self.payload.to_dict()

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "header": header,
            }
        )
        if request_id is not UNSET:
            field_dict["request_id"] = request_id
        if payload is not UNSET:
            field_dict["payload"] = payload

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.cfn_header import CfnHeader
        from ..models.negotiation_request_payload import NegotiationRequestPayload

        d = dict(src_dict)
        header = CfnHeader.from_dict(d.pop("header"))

        request_id = d.pop("request_id", UNSET)

        _payload = d.pop("payload", UNSET)
        payload: NegotiationRequestPayload | Unset
        if isinstance(_payload, Unset):
            payload = UNSET
        else:
            payload = NegotiationRequestPayload.from_dict(_payload)

        negotiation_request = cls(
            header=header,
            request_id=request_id,
            payload=payload,
        )

        negotiation_request.additional_properties = d
        return negotiation_request

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
