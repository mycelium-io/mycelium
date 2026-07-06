from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, TypeVar

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

if TYPE_CHECKING:
    from ..models.app_ingest_ce_metrics_request_attributes import (
        AppIngestCEMetricsRequestAttributes,
    )
    from ..models.app_metric_data_point import AppMetricDataPoint


T = TypeVar("T", bound="AppIngestCEMetricsRequest")


@_attrs_define
class AppIngestCEMetricsRequest:
    """
    Attributes:
        attributes (AppIngestCEMetricsRequestAttributes | Unset):
        metrics (list[AppMetricDataPoint] | Unset):
    """

    attributes: AppIngestCEMetricsRequestAttributes | Unset = UNSET
    metrics: list[AppMetricDataPoint] | Unset = UNSET
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        attributes: dict[str, Any] | Unset = UNSET
        if not isinstance(self.attributes, Unset):
            attributes = self.attributes.to_dict()

        metrics: list[dict[str, Any]] | Unset = UNSET
        if not isinstance(self.metrics, Unset):
            metrics = []
            for metrics_item_data in self.metrics:
                metrics_item = metrics_item_data.to_dict()
                metrics.append(metrics_item)

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update({})
        if attributes is not UNSET:
            field_dict["attributes"] = attributes
        if metrics is not UNSET:
            field_dict["metrics"] = metrics

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.app_ingest_ce_metrics_request_attributes import (
            AppIngestCEMetricsRequestAttributes,
        )
        from ..models.app_metric_data_point import AppMetricDataPoint

        d = dict(src_dict)
        _attributes = d.pop("attributes", UNSET)
        attributes: AppIngestCEMetricsRequestAttributes | Unset
        if isinstance(_attributes, Unset):
            attributes = UNSET
        else:
            attributes = AppIngestCEMetricsRequestAttributes.from_dict(_attributes)

        _metrics = d.pop("metrics", UNSET)
        metrics: list[AppMetricDataPoint] | Unset = UNSET
        if _metrics is not UNSET:
            metrics = []
            for metrics_item_data in _metrics:
                metrics_item = AppMetricDataPoint.from_dict(metrics_item_data)

                metrics.append(metrics_item)

        app_ingest_ce_metrics_request = cls(
            attributes=attributes,
            metrics=metrics,
        )

        app_ingest_ce_metrics_request.additional_properties = d
        return app_ingest_ce_metrics_request

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
