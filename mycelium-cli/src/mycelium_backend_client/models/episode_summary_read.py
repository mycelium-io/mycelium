from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, TypeVar, cast

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

if TYPE_CHECKING:
    from ..models.episode_metrics_read import EpisodeMetricsRead
    from ..models.episode_summary_read_assignments_type_0 import EpisodeSummaryReadAssignmentsType0


T = TypeVar("T", bound="EpisodeSummaryRead")


@_attrs_define
class EpisodeSummaryRead:
    """
    Attributes:
        short_id (str):
        episode (str):
        topic (str):
        outcome (str):
        subkind (None | str | Unset):
        participants (list[str] | Unset):
        metrics (EpisodeMetricsRead | None | Unset):
        assignments (EpisodeSummaryReadAssignmentsType0 | None | Unset):
        plan_file (None | str | Unset):
        message_count (int | Unset):  Default: 0.
        updated_at (str | Unset):  Default: ''.
        updated_by (str | Unset):  Default: ''.
    """

    short_id: str
    episode: str
    topic: str
    outcome: str
    subkind: None | str | Unset = UNSET
    participants: list[str] | Unset = UNSET
    metrics: EpisodeMetricsRead | None | Unset = UNSET
    assignments: EpisodeSummaryReadAssignmentsType0 | None | Unset = UNSET
    plan_file: None | str | Unset = UNSET
    message_count: int | Unset = 0
    updated_at: str | Unset = ""
    updated_by: str | Unset = ""
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        from ..models.episode_metrics_read import EpisodeMetricsRead
        from ..models.episode_summary_read_assignments_type_0 import (
            EpisodeSummaryReadAssignmentsType0,
        )

        short_id = self.short_id

        episode = self.episode

        topic = self.topic

        outcome = self.outcome

        subkind: None | str | Unset
        if isinstance(self.subkind, Unset):
            subkind = UNSET
        else:
            subkind = self.subkind

        participants: list[str] | Unset = UNSET
        if not isinstance(self.participants, Unset):
            participants = self.participants

        metrics: dict[str, Any] | None | Unset
        if isinstance(self.metrics, Unset):
            metrics = UNSET
        elif isinstance(self.metrics, EpisodeMetricsRead):
            metrics = self.metrics.to_dict()
        else:
            metrics = self.metrics

        assignments: dict[str, Any] | None | Unset
        if isinstance(self.assignments, Unset):
            assignments = UNSET
        elif isinstance(self.assignments, EpisodeSummaryReadAssignmentsType0):
            assignments = self.assignments.to_dict()
        else:
            assignments = self.assignments

        plan_file: None | str | Unset
        if isinstance(self.plan_file, Unset):
            plan_file = UNSET
        else:
            plan_file = self.plan_file

        message_count = self.message_count

        updated_at = self.updated_at

        updated_by = self.updated_by

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "short_id": short_id,
                "episode": episode,
                "topic": topic,
                "outcome": outcome,
            }
        )
        if subkind is not UNSET:
            field_dict["subkind"] = subkind
        if participants is not UNSET:
            field_dict["participants"] = participants
        if metrics is not UNSET:
            field_dict["metrics"] = metrics
        if assignments is not UNSET:
            field_dict["assignments"] = assignments
        if plan_file is not UNSET:
            field_dict["plan_file"] = plan_file
        if message_count is not UNSET:
            field_dict["message_count"] = message_count
        if updated_at is not UNSET:
            field_dict["updated_at"] = updated_at
        if updated_by is not UNSET:
            field_dict["updated_by"] = updated_by

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.episode_metrics_read import EpisodeMetricsRead
        from ..models.episode_summary_read_assignments_type_0 import (
            EpisodeSummaryReadAssignmentsType0,
        )

        d = dict(src_dict)
        short_id = d.pop("short_id")

        episode = d.pop("episode")

        topic = d.pop("topic")

        outcome = d.pop("outcome")

        def _parse_subkind(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        subkind = _parse_subkind(d.pop("subkind", UNSET))

        participants = cast(list[str], d.pop("participants", UNSET))

        def _parse_metrics(data: object) -> EpisodeMetricsRead | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            try:
                if not isinstance(data, dict):
                    raise TypeError()
                metrics_type_0 = EpisodeMetricsRead.from_dict(data)

                return metrics_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(EpisodeMetricsRead | None | Unset, data)

        metrics = _parse_metrics(d.pop("metrics", UNSET))

        def _parse_assignments(data: object) -> EpisodeSummaryReadAssignmentsType0 | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            try:
                if not isinstance(data, dict):
                    raise TypeError()
                assignments_type_0 = EpisodeSummaryReadAssignmentsType0.from_dict(data)

                return assignments_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(EpisodeSummaryReadAssignmentsType0 | None | Unset, data)

        assignments = _parse_assignments(d.pop("assignments", UNSET))

        def _parse_plan_file(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        plan_file = _parse_plan_file(d.pop("plan_file", UNSET))

        message_count = d.pop("message_count", UNSET)

        updated_at = d.pop("updated_at", UNSET)

        updated_by = d.pop("updated_by", UNSET)

        episode_summary_read = cls(
            short_id=short_id,
            episode=episode,
            topic=topic,
            outcome=outcome,
            subkind=subkind,
            participants=participants,
            metrics=metrics,
            assignments=assignments,
            plan_file=plan_file,
            message_count=message_count,
            updated_at=updated_at,
            updated_by=updated_by,
        )

        episode_summary_read.additional_properties = d
        return episode_summary_read

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
