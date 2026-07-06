from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar

from attrs import define as _attrs_define
from attrs import field as _attrs_field

T = TypeVar("T", bound="CognitionagentclientExtractionPayloadData")


@_attrs_define
class CognitionagentclientExtractionPayloadData:
    """Data contains the extraction payload and its structure depends on Metadata.Format.

    Supported formats: "observe-sdk-otel", "openclaw" and "otel-trace".

    1. format = "observe-sdk-otel"
       - Data MUST be a JSON array of ExtractionDataRecord objects.
       - Example:
    [
      { TraceId, SpanId, ParentSpanId, SpanName, ServiceName, SpanAttributes, Duration }
    ]

    2. format = "openclaw"
       - Data is an opaque JSON payload.
       - The structure is not interpreted or validated by this service and is processed as-is.

    Clients MUST ensure the Data field matches the structure required by the specified Metadata.Format.

    """

    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        cognitionagentclient_extraction_payload_data = cls()

        cognitionagentclient_extraction_payload_data.additional_properties = d
        return cognitionagentclient_extraction_payload_data

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
