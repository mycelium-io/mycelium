from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, TypeVar, cast

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

if TYPE_CHECKING:
    from ..models.app_metric_series_attributes import AppMetricSeriesAttributes


T = TypeVar("T", bound="AppMetricSeries")


@_attrs_define
class AppMetricSeries:
    """
    Attributes:
        agent_id (str | Unset):
        attributes (AppMetricSeriesAttributes | Unset): Attributes (shared across all datapoints in this series)
        ce_id (str | Unset):
        datapoints (list[list[Any]] | Unset): Datapoints: array of [timestamp, value] pairs
            Format: [["2026-05-27T10:00:00Z", 123.45], ["2026-05-27T10:01:00Z", 456.78]]
        mas_id (str | Unset):
        metric_name (str | Unset):
        workspace_id (str | Unset): MAS fields (populated for MAS metrics)
    """

    agent_id: str | Unset = UNSET
    attributes: AppMetricSeriesAttributes | Unset = UNSET
    ce_id: str | Unset = UNSET
    datapoints: list[list[Any]] | Unset = UNSET
    mas_id: str | Unset = UNSET
    metric_name: str | Unset = UNSET
    workspace_id: str | Unset = UNSET
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        agent_id = self.agent_id

        attributes: dict[str, Any] | Unset = UNSET
        if not isinstance(self.attributes, Unset):
            attributes = self.attributes.to_dict()

        ce_id = self.ce_id

        datapoints: list[list[Any]] | Unset = UNSET
        if not isinstance(self.datapoints, Unset):
            datapoints = []
            for datapoints_item_data in self.datapoints:
                datapoints_item = datapoints_item_data

                datapoints.append(datapoints_item)

        mas_id = self.mas_id

        metric_name = self.metric_name

        workspace_id = self.workspace_id

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update({})
        if agent_id is not UNSET:
            field_dict["agent_id"] = agent_id
        if attributes is not UNSET:
            field_dict["attributes"] = attributes
        if ce_id is not UNSET:
            field_dict["ce_id"] = ce_id
        if datapoints is not UNSET:
            field_dict["datapoints"] = datapoints
        if mas_id is not UNSET:
            field_dict["mas_id"] = mas_id
        if metric_name is not UNSET:
            field_dict["metric_name"] = metric_name
        if workspace_id is not UNSET:
            field_dict["workspace_id"] = workspace_id

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.app_metric_series_attributes import AppMetricSeriesAttributes

        d = dict(src_dict)
        agent_id = d.pop("agent_id", UNSET)

        _attributes = d.pop("attributes", UNSET)
        attributes: AppMetricSeriesAttributes | Unset
        if isinstance(_attributes, Unset):
            attributes = UNSET
        else:
            attributes = AppMetricSeriesAttributes.from_dict(_attributes)

        ce_id = d.pop("ce_id", UNSET)

        _datapoints = d.pop("datapoints", UNSET)
        datapoints: list[list[Any]] | Unset = UNSET
        if _datapoints is not UNSET:
            datapoints = []
            for datapoints_item_data in _datapoints:
                datapoints_item = cast(list[Any], datapoints_item_data)

                datapoints.append(datapoints_item)

        mas_id = d.pop("mas_id", UNSET)

        metric_name = d.pop("metric_name", UNSET)

        workspace_id = d.pop("workspace_id", UNSET)

        app_metric_series = cls(
            agent_id=agent_id,
            attributes=attributes,
            ce_id=ce_id,
            datapoints=datapoints,
            mas_id=mas_id,
            metric_name=metric_name,
            workspace_id=workspace_id,
        )

        app_metric_series.additional_properties = d
        return app_metric_series

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
