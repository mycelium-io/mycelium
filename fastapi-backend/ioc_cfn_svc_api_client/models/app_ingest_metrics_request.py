from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, TypeVar

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

if TYPE_CHECKING:
    from ..models.app_ingest_metrics_request_attributes import AppIngestMetricsRequestAttributes
    from ..models.app_metric_data_point import AppMetricDataPoint


T = TypeVar("T", bound="AppIngestMetricsRequest")


@_attrs_define
class AppIngestMetricsRequest:
    """
    Attributes:
        agent_id (str | Unset):
        attributes (AppIngestMetricsRequestAttributes | Unset): Common fields
        ce_id (str | Unset): CE metrics fields (mutually exclusive with MAS fields)
        mas_id (str | Unset):
        metrics (list[AppMetricDataPoint] | Unset):
        workspace_id (str | Unset): MAS metrics fields (mutually exclusive with CE fields)
    """

    agent_id: str | Unset = UNSET
    attributes: AppIngestMetricsRequestAttributes | Unset = UNSET
    ce_id: str | Unset = UNSET
    mas_id: str | Unset = UNSET
    metrics: list[AppMetricDataPoint] | Unset = UNSET
    workspace_id: str | Unset = UNSET
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        agent_id = self.agent_id

        attributes: dict[str, Any] | Unset = UNSET
        if not isinstance(self.attributes, Unset):
            attributes = self.attributes.to_dict()

        ce_id = self.ce_id

        mas_id = self.mas_id

        metrics: list[dict[str, Any]] | Unset = UNSET
        if not isinstance(self.metrics, Unset):
            metrics = []
            for metrics_item_data in self.metrics:
                metrics_item = metrics_item_data.to_dict()
                metrics.append(metrics_item)

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
        if mas_id is not UNSET:
            field_dict["mas_id"] = mas_id
        if metrics is not UNSET:
            field_dict["metrics"] = metrics
        if workspace_id is not UNSET:
            field_dict["workspace_id"] = workspace_id

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.app_ingest_metrics_request_attributes import AppIngestMetricsRequestAttributes
        from ..models.app_metric_data_point import AppMetricDataPoint

        d = dict(src_dict)
        agent_id = d.pop("agent_id", UNSET)

        _attributes = d.pop("attributes", UNSET)
        attributes: AppIngestMetricsRequestAttributes | Unset
        if isinstance(_attributes, Unset):
            attributes = UNSET
        else:
            attributes = AppIngestMetricsRequestAttributes.from_dict(_attributes)

        ce_id = d.pop("ce_id", UNSET)

        mas_id = d.pop("mas_id", UNSET)

        _metrics = d.pop("metrics", UNSET)
        metrics: list[AppMetricDataPoint] | Unset = UNSET
        if _metrics is not UNSET:
            metrics = []
            for metrics_item_data in _metrics:
                metrics_item = AppMetricDataPoint.from_dict(metrics_item_data)

                metrics.append(metrics_item)

        workspace_id = d.pop("workspace_id", UNSET)

        app_ingest_metrics_request = cls(
            agent_id=agent_id,
            attributes=attributes,
            ce_id=ce_id,
            mas_id=mas_id,
            metrics=metrics,
            workspace_id=workspace_id,
        )

        app_ingest_metrics_request.additional_properties = d
        return app_ingest_metrics_request

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
