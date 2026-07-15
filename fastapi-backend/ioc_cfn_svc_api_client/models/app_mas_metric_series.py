from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, TypeVar, cast

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

if TYPE_CHECKING:
    from ..models.app_mas_metric_series_attributes import AppMASMetricSeriesAttributes


T = TypeVar("T", bound="AppMASMetricSeries")


@_attrs_define
class AppMASMetricSeries:
    """
    Attributes:
        agent_id (str | Unset):
        attributes (AppMASMetricSeriesAttributes | Unset):
        datapoints (list[list[Any]] | Unset):
        metric_name (str | Unset):
    """

    agent_id: str | Unset = UNSET
    attributes: AppMASMetricSeriesAttributes | Unset = UNSET
    datapoints: list[list[Any]] | Unset = UNSET
    metric_name: str | Unset = UNSET
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        agent_id = self.agent_id

        attributes: dict[str, Any] | Unset = UNSET
        if not isinstance(self.attributes, Unset):
            attributes = self.attributes.to_dict()

        datapoints: list[list[Any]] | Unset = UNSET
        if not isinstance(self.datapoints, Unset):
            datapoints = []
            for datapoints_item_data in self.datapoints:
                datapoints_item = datapoints_item_data

                datapoints.append(datapoints_item)

        metric_name = self.metric_name

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update({})
        if agent_id is not UNSET:
            field_dict["agent_id"] = agent_id
        if attributes is not UNSET:
            field_dict["attributes"] = attributes
        if datapoints is not UNSET:
            field_dict["datapoints"] = datapoints
        if metric_name is not UNSET:
            field_dict["metric_name"] = metric_name

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.app_mas_metric_series_attributes import AppMASMetricSeriesAttributes

        d = dict(src_dict)
        agent_id = d.pop("agent_id", UNSET)

        _attributes = d.pop("attributes", UNSET)
        attributes: AppMASMetricSeriesAttributes | Unset
        if isinstance(_attributes, Unset):
            attributes = UNSET
        else:
            attributes = AppMASMetricSeriesAttributes.from_dict(_attributes)

        _datapoints = d.pop("datapoints", UNSET)
        datapoints: list[list[Any]] | Unset = UNSET
        if _datapoints is not UNSET:
            datapoints = []
            for datapoints_item_data in _datapoints:
                datapoints_item = cast(list[Any], datapoints_item_data)

                datapoints.append(datapoints_item)

        metric_name = d.pop("metric_name", UNSET)

        app_mas_metric_series = cls(
            agent_id=agent_id,
            attributes=attributes,
            datapoints=datapoints,
            metric_name=metric_name,
        )

        app_mas_metric_series.additional_properties = d
        return app_mas_metric_series

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
