from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, TypeVar

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

if TYPE_CHECKING:
    from ..models.cfn_header import CfnHeader
    from ..models.extraction_payload import ExtractionPayload


T = TypeVar("T", bound="ExtractionRequest")


@_attrs_define
class ExtractionRequest:
    """
    Attributes:
        header (CfnHeader):
        payload (ExtractionPayload):
        request_id (str | Unset):
    """

    header: CfnHeader
    payload: ExtractionPayload
    request_id: str | Unset = UNSET
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        header = self.header.to_dict()

        payload = self.payload.to_dict()

        request_id = self.request_id

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "header": header,
                "payload": payload,
            }
        )
        if request_id is not UNSET:
            field_dict["request_id"] = request_id

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.cfn_header import CfnHeader
        from ..models.extraction_payload import ExtractionPayload

        d = dict(src_dict)
        header = CfnHeader.from_dict(d.pop("header"))

        payload = ExtractionPayload.from_dict(d.pop("payload"))

        request_id = d.pop("request_id", UNSET)

        extraction_request = cls(
            header=header,
            payload=payload,
            request_id=request_id,
        )

        extraction_request.additional_properties = d
        return extraction_request

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
