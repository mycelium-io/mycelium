from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, TypeVar

from attrs import define as _attrs_define
from attrs import field as _attrs_field

if TYPE_CHECKING:
    from ..models.extraction_payload_data_item import ExtractionPayloadDataItem
    from ..models.extraction_payload_metadata import ExtractionPayloadMetadata


T = TypeVar("T", bound="ExtractionPayload")


@_attrs_define
class ExtractionPayload:
    """
    Attributes:
        metadata (ExtractionPayloadMetadata):
        data (list[ExtractionPayloadDataItem]): Extraction payload as a list of JSON objects. The objects are not
            validated by this service and are processed as-is. Clients must ensure each object matches the format specified
            by `metadata.format`.
    """

    metadata: ExtractionPayloadMetadata
    data: list[ExtractionPayloadDataItem]
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        metadata = self.metadata.to_dict()

        data = []
        for data_item_data in self.data:
            data_item = data_item_data.to_dict()
            data.append(data_item)

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "metadata": metadata,
                "data": data,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.extraction_payload_data_item import ExtractionPayloadDataItem
        from ..models.extraction_payload_metadata import ExtractionPayloadMetadata

        d = dict(src_dict)
        metadata = ExtractionPayloadMetadata.from_dict(d.pop("metadata"))

        data = []
        _data = d.pop("data")
        for data_item_data in _data:
            data_item = ExtractionPayloadDataItem.from_dict(data_item_data)

            data.append(data_item)

        extraction_payload = cls(
            metadata=metadata,
            data=data,
        )

        extraction_payload.additional_properties = d
        return extraction_payload

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
