from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, TypeVar

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

if TYPE_CHECKING:
    from ..models.app_ce_metric_group import AppCEMetricGroup


T = TypeVar("T", bound="AppMASMetricsQueryResponse")


@_attrs_define
class AppMASMetricsQueryResponse:
    """
    Attributes:
        ces (list[AppCEMetricGroup] | Unset):
        end_time (str | Unset):
        mas_id (str | Unset):
        start_time (str | Unset):
        workspace_id (str | Unset):
    """

    ces: list[AppCEMetricGroup] | Unset = UNSET
    end_time: str | Unset = UNSET
    mas_id: str | Unset = UNSET
    start_time: str | Unset = UNSET
    workspace_id: str | Unset = UNSET
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        ces: list[dict[str, Any]] | Unset = UNSET
        if not isinstance(self.ces, Unset):
            ces = []
            for ces_item_data in self.ces:
                ces_item = ces_item_data.to_dict()
                ces.append(ces_item)

        end_time = self.end_time

        mas_id = self.mas_id

        start_time = self.start_time

        workspace_id = self.workspace_id

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update({})
        if ces is not UNSET:
            field_dict["ces"] = ces
        if end_time is not UNSET:
            field_dict["end_time"] = end_time
        if mas_id is not UNSET:
            field_dict["mas_id"] = mas_id
        if start_time is not UNSET:
            field_dict["start_time"] = start_time
        if workspace_id is not UNSET:
            field_dict["workspace_id"] = workspace_id

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.app_ce_metric_group import AppCEMetricGroup

        d = dict(src_dict)
        _ces = d.pop("ces", UNSET)
        ces: list[AppCEMetricGroup] | Unset = UNSET
        if _ces is not UNSET:
            ces = []
            for ces_item_data in _ces:
                ces_item = AppCEMetricGroup.from_dict(ces_item_data)

                ces.append(ces_item)

        end_time = d.pop("end_time", UNSET)

        mas_id = d.pop("mas_id", UNSET)

        start_time = d.pop("start_time", UNSET)

        workspace_id = d.pop("workspace_id", UNSET)

        app_mas_metrics_query_response = cls(
            ces=ces,
            end_time=end_time,
            mas_id=mas_id,
            start_time=start_time,
            workspace_id=workspace_id,
        )

        app_mas_metrics_query_response.additional_properties = d
        return app_mas_metrics_query_response

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
