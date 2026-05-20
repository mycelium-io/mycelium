from __future__ import annotations

import datetime
from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, TypeVar

from attrs import define as _attrs_define
from attrs import field as _attrs_field
from dateutil.parser import isoparse

if TYPE_CHECKING:
    from ..models.ingest_event import IngestEvent


T = TypeVar("T", bound="IngestLogResponse")


@_attrs_define
class IngestLogResponse:
    """
    Attributes:
        buffer_started_at (datetime.datetime):
        events (list[IngestEvent]):
        total_events (int):
    """

    buffer_started_at: datetime.datetime
    events: list[IngestEvent]
    total_events: int
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        buffer_started_at = self.buffer_started_at.isoformat()

        events = []
        for events_item_data in self.events:
            events_item = events_item_data.to_dict()
            events.append(events_item)

        total_events = self.total_events

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "buffer_started_at": buffer_started_at,
                "events": events,
                "total_events": total_events,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.ingest_event import IngestEvent

        d = dict(src_dict)
        buffer_started_at = isoparse(d.pop("buffer_started_at"))

        events = []
        _events = d.pop("events")
        for events_item_data in _events:
            events_item = IngestEvent.from_dict(events_item_data)

            events.append(events_item)

        total_events = d.pop("total_events")

        ingest_log_response = cls(
            buffer_started_at=buffer_started_at,
            events=events,
            total_events=total_events,
        )

        ingest_log_response.additional_properties = d
        return ingest_log_response

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
