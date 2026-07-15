from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, TypeVar

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

if TYPE_CHECKING:
    from ..models.app_metric_data_point_attributes import AppMetricDataPointAttributes


T = TypeVar("T", bound="AppMetricDataPoint")


@_attrs_define
class AppMetricDataPoint:
    """
    Attributes:
        attributes (AppMetricDataPointAttributes | Unset):
        name (str | Unset):
        timestamp (str | Unset):
        value (float | Unset):
    """

    attributes: AppMetricDataPointAttributes | Unset = UNSET
    name: str | Unset = UNSET
    timestamp: str | Unset = UNSET
    value: float | Unset = UNSET
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        attributes: dict[str, Any] | Unset = UNSET
        if not isinstance(self.attributes, Unset):
            attributes = self.attributes.to_dict()

        name = self.name

        timestamp = self.timestamp

        value = self.value

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update({})
        if attributes is not UNSET:
            field_dict["attributes"] = attributes
        if name is not UNSET:
            field_dict["name"] = name
        if timestamp is not UNSET:
            field_dict["timestamp"] = timestamp
        if value is not UNSET:
            field_dict["value"] = value

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.app_metric_data_point_attributes import AppMetricDataPointAttributes

        d = dict(src_dict)
        _attributes = d.pop("attributes", UNSET)
        attributes: AppMetricDataPointAttributes | Unset
        if isinstance(_attributes, Unset):
            attributes = UNSET
        else:
            attributes = AppMetricDataPointAttributes.from_dict(_attributes)

        name = d.pop("name", UNSET)

        timestamp = d.pop("timestamp", UNSET)

        value = d.pop("value", UNSET)

        app_metric_data_point = cls(
            attributes=attributes,
            name=name,
            timestamp=timestamp,
            value=value,
        )

        app_metric_data_point.additional_properties = d
        return app_metric_data_point

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
