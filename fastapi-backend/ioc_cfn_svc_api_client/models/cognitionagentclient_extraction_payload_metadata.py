from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

T = TypeVar("T", bound="CognitionagentclientExtractionPayloadMetadata")


@_attrs_define
class CognitionagentclientExtractionPayloadMetadata:
    """
    Attributes:
        format_ (str | Unset): Format specifies how the Data field should be interpreted.

            Supported values:
            - "observe-sdk-otel": Data is a JSON array of ExtractionDataRecord
            - "otel-trace": Data is a grouped OTel trace payload pushed by cfn-svc
            - "openclaw": Data is an opaque JSON payload
    """

    format_: str | Unset = UNSET
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        format_ = self.format_

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update({})
        if format_ is not UNSET:
            field_dict["format"] = format_

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        format_ = d.pop("format", UNSET)

        cognitionagentclient_extraction_payload_metadata = cls(
            format_=format_,
        )

        cognitionagentclient_extraction_payload_metadata.additional_properties = d
        return cognitionagentclient_extraction_payload_metadata

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
