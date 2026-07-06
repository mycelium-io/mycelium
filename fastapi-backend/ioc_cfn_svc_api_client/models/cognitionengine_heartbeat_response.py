from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

T = TypeVar("T", bound="CognitionengineHeartbeatResponse")


@_attrs_define
class CognitionengineHeartbeatResponse:
    """
    Attributes:
        last_seen (str | Unset):
        status (str | Unset):
    """

    last_seen: str | Unset = UNSET
    status: str | Unset = UNSET
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        last_seen = self.last_seen

        status = self.status

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update({})
        if last_seen is not UNSET:
            field_dict["last_seen"] = last_seen
        if status is not UNSET:
            field_dict["status"] = status

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        last_seen = d.pop("last_seen", UNSET)

        status = d.pop("status", UNSET)

        cognitionengine_heartbeat_response = cls(
            last_seen=last_seen,
            status=status,
        )

        cognitionengine_heartbeat_response.additional_properties = d
        return cognitionengine_heartbeat_response

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
