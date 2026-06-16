from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar

from attrs import define as _attrs_define
from attrs import field as _attrs_field

T = TypeVar("T", bound="IngestStatsAggregate")


@_attrs_define
class IngestStatsAggregate:
    """
    Attributes:
        events (int):
        estimated_cfn_knowledge_input_tokens (int):
        payload_bytes (int):
    """

    events: int
    estimated_cfn_knowledge_input_tokens: int
    payload_bytes: int
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        events = self.events

        estimated_cfn_knowledge_input_tokens = self.estimated_cfn_knowledge_input_tokens

        payload_bytes = self.payload_bytes

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "events": events,
                "estimated_cfn_knowledge_input_tokens": estimated_cfn_knowledge_input_tokens,
                "payload_bytes": payload_bytes,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        events = d.pop("events")

        estimated_cfn_knowledge_input_tokens = d.pop("estimated_cfn_knowledge_input_tokens")

        payload_bytes = d.pop("payload_bytes")

        ingest_stats_aggregate = cls(
            events=events,
            estimated_cfn_knowledge_input_tokens=estimated_cfn_knowledge_input_tokens,
            payload_bytes=payload_bytes,
        )

        ingest_stats_aggregate.additional_properties = d
        return ingest_stats_aggregate

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
