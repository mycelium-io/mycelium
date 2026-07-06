from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, TypeVar

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

if TYPE_CHECKING:
    from ..models.app_mas_metric_series import AppMASMetricSeries


T = TypeVar("T", bound="AppCEMetricGroup")


@_attrs_define
class AppCEMetricGroup:
    """
    Attributes:
        ce_id (str | Unset):
        series (list[AppMASMetricSeries] | Unset):
    """

    ce_id: str | Unset = UNSET
    series: list[AppMASMetricSeries] | Unset = UNSET
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        ce_id = self.ce_id

        series: list[dict[str, Any]] | Unset = UNSET
        if not isinstance(self.series, Unset):
            series = []
            for series_item_data in self.series:
                series_item = series_item_data.to_dict()
                series.append(series_item)

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update({})
        if ce_id is not UNSET:
            field_dict["ce_id"] = ce_id
        if series is not UNSET:
            field_dict["series"] = series

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.app_mas_metric_series import AppMASMetricSeries

        d = dict(src_dict)
        ce_id = d.pop("ce_id", UNSET)

        _series = d.pop("series", UNSET)
        series: list[AppMASMetricSeries] | Unset = UNSET
        if _series is not UNSET:
            series = []
            for series_item_data in _series:
                series_item = AppMASMetricSeries.from_dict(series_item_data)

                series.append(series_item)

        app_ce_metric_group = cls(
            ce_id=ce_id,
            series=series,
        )

        app_ce_metric_group.additional_properties = d
        return app_ce_metric_group

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
