from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, TypeVar

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

if TYPE_CHECKING:
    from ..models.cognitionagentclient_extraction_payload_data import (
        CognitionagentclientExtractionPayloadData,
    )
    from ..models.cognitionagentclient_extraction_payload_metadata import (
        CognitionagentclientExtractionPayloadMetadata,
    )


T = TypeVar("T", bound="CognitionagentclientExtractionPayload")


@_attrs_define
class CognitionagentclientExtractionPayload:
    """
    Attributes:
        data (CognitionagentclientExtractionPayloadData | Unset): Data contains the extraction payload and its structure
            depends on Metadata.Format.

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
        metadata (CognitionagentclientExtractionPayloadMetadata | Unset):
    """

    data: CognitionagentclientExtractionPayloadData | Unset = UNSET
    metadata: CognitionagentclientExtractionPayloadMetadata | Unset = UNSET
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        data: dict[str, Any] | Unset = UNSET
        if not isinstance(self.data, Unset):
            data = self.data.to_dict()

        metadata: dict[str, Any] | Unset = UNSET
        if not isinstance(self.metadata, Unset):
            metadata = self.metadata.to_dict()

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update({})
        if data is not UNSET:
            field_dict["data"] = data
        if metadata is not UNSET:
            field_dict["metadata"] = metadata

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.cognitionagentclient_extraction_payload_data import (
            CognitionagentclientExtractionPayloadData,
        )
        from ..models.cognitionagentclient_extraction_payload_metadata import (
            CognitionagentclientExtractionPayloadMetadata,
        )

        d = dict(src_dict)
        _data = d.pop("data", UNSET)
        data: CognitionagentclientExtractionPayloadData | Unset
        if isinstance(_data, Unset):
            data = UNSET
        else:
            data = CognitionagentclientExtractionPayloadData.from_dict(_data)

        _metadata = d.pop("metadata", UNSET)
        metadata: CognitionagentclientExtractionPayloadMetadata | Unset
        if isinstance(_metadata, Unset):
            metadata = UNSET
        else:
            metadata = CognitionagentclientExtractionPayloadMetadata.from_dict(_metadata)

        cognitionagentclient_extraction_payload = cls(
            data=data,
            metadata=metadata,
        )

        cognitionagentclient_extraction_payload.additional_properties = d
        return cognitionagentclient_extraction_payload

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
