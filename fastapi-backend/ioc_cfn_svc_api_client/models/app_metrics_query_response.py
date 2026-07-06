from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, TypeVar

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

if TYPE_CHECKING:
    from ..models.app_metric_result_set import AppMetricResultSet


T = TypeVar("T", bound="AppMetricsQueryResponse")


@_attrs_define
class AppMetricsQueryResponse:
    """
    Attributes:
        ce_id (str | Unset):
        ce_metrics (AppMetricResultSet | Unset):
        mas_metrics (AppMetricResultSet | Unset):
    """

    ce_id: str | Unset = UNSET
    ce_metrics: AppMetricResultSet | Unset = UNSET
    mas_metrics: AppMetricResultSet | Unset = UNSET
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        ce_id = self.ce_id

        ce_metrics: dict[str, Any] | Unset = UNSET
        if not isinstance(self.ce_metrics, Unset):
            ce_metrics = self.ce_metrics.to_dict()

        mas_metrics: dict[str, Any] | Unset = UNSET
        if not isinstance(self.mas_metrics, Unset):
            mas_metrics = self.mas_metrics.to_dict()

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update({})
        if ce_id is not UNSET:
            field_dict["ce_id"] = ce_id
        if ce_metrics is not UNSET:
            field_dict["ce_metrics"] = ce_metrics
        if mas_metrics is not UNSET:
            field_dict["mas_metrics"] = mas_metrics

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.app_metric_result_set import AppMetricResultSet

        d = dict(src_dict)
        ce_id = d.pop("ce_id", UNSET)

        _ce_metrics = d.pop("ce_metrics", UNSET)
        ce_metrics: AppMetricResultSet | Unset
        if isinstance(_ce_metrics, Unset):
            ce_metrics = UNSET
        else:
            ce_metrics = AppMetricResultSet.from_dict(_ce_metrics)

        _mas_metrics = d.pop("mas_metrics", UNSET)
        mas_metrics: AppMetricResultSet | Unset
        if isinstance(_mas_metrics, Unset):
            mas_metrics = UNSET
        else:
            mas_metrics = AppMetricResultSet.from_dict(_mas_metrics)

        app_metrics_query_response = cls(
            ce_id=ce_id,
            ce_metrics=ce_metrics,
            mas_metrics=mas_metrics,
        )

        app_metrics_query_response.additional_properties = d
        return app_metrics_query_response

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
