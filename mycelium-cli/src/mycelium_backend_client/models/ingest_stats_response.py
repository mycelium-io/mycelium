from __future__ import annotations

import datetime
from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, TypeVar, cast

from attrs import define as _attrs_define
from attrs import field as _attrs_field
from dateutil.parser import isoparse

if TYPE_CHECKING:
    from ..models.ingest_stats_aggregate import IngestStatsAggregate
    from ..models.ingest_stats_response_by_agent import IngestStatsResponseByAgent
    from ..models.ingest_stats_response_by_mas import IngestStatsResponseByMas


T = TypeVar("T", bound="IngestStatsResponse")


@_attrs_define
class IngestStatsResponse:
    """
    Attributes:
        buffer_started_at (datetime.datetime):
        last_event_at (datetime.datetime | None):
        total (IngestStatsAggregate):
        last_hour (IngestStatsAggregate):
        by_mas (IngestStatsResponseByMas):
        by_agent (IngestStatsResponseByAgent):
    """

    buffer_started_at: datetime.datetime
    last_event_at: datetime.datetime | None
    total: IngestStatsAggregate
    last_hour: IngestStatsAggregate
    by_mas: IngestStatsResponseByMas
    by_agent: IngestStatsResponseByAgent
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        buffer_started_at = self.buffer_started_at.isoformat()

        last_event_at: None | str
        if isinstance(self.last_event_at, datetime.datetime):
            last_event_at = self.last_event_at.isoformat()
        else:
            last_event_at = self.last_event_at

        total = self.total.to_dict()

        last_hour = self.last_hour.to_dict()

        by_mas = self.by_mas.to_dict()

        by_agent = self.by_agent.to_dict()

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "buffer_started_at": buffer_started_at,
                "last_event_at": last_event_at,
                "total": total,
                "last_hour": last_hour,
                "by_mas": by_mas,
                "by_agent": by_agent,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.ingest_stats_aggregate import IngestStatsAggregate
        from ..models.ingest_stats_response_by_agent import IngestStatsResponseByAgent
        from ..models.ingest_stats_response_by_mas import IngestStatsResponseByMas

        d = dict(src_dict)
        buffer_started_at = isoparse(d.pop("buffer_started_at"))

        def _parse_last_event_at(data: object) -> datetime.datetime | None:
            if data is None:
                return data
            try:
                if not isinstance(data, str):
                    raise TypeError()
                last_event_at_type_0 = isoparse(data)

                return last_event_at_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(datetime.datetime | None, data)

        last_event_at = _parse_last_event_at(d.pop("last_event_at"))

        total = IngestStatsAggregate.from_dict(d.pop("total"))

        last_hour = IngestStatsAggregate.from_dict(d.pop("last_hour"))

        by_mas = IngestStatsResponseByMas.from_dict(d.pop("by_mas"))

        by_agent = IngestStatsResponseByAgent.from_dict(d.pop("by_agent"))

        ingest_stats_response = cls(
            buffer_started_at=buffer_started_at,
            last_event_at=last_event_at,
            total=total,
            last_hour=last_hour,
            by_mas=by_mas,
            by_agent=by_agent,
        )

        ingest_stats_response.additional_properties = d
        return ingest_stats_response

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
