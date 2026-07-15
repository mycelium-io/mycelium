from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

T = TypeVar("T", bound="L9L9HeaderPolicy")


@_attrs_define
class L9L9HeaderPolicy:
    """
    Attributes:
        propagation (str | Unset): Propagation corresponds to the JSON schema field "propagation".
        retention_policy (str | Unset): RetentionPolicy corresponds to the JSON schema field "retention_policy".
        sensitivity (str | Unset): Sensitivity corresponds to the JSON schema field "sensitivity".
    """

    propagation: str | Unset = UNSET
    retention_policy: str | Unset = UNSET
    sensitivity: str | Unset = UNSET
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        propagation = self.propagation

        retention_policy = self.retention_policy

        sensitivity = self.sensitivity

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update({})
        if propagation is not UNSET:
            field_dict["propagation"] = propagation
        if retention_policy is not UNSET:
            field_dict["retention_policy"] = retention_policy
        if sensitivity is not UNSET:
            field_dict["sensitivity"] = sensitivity

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        propagation = d.pop("propagation", UNSET)

        retention_policy = d.pop("retention_policy", UNSET)

        sensitivity = d.pop("sensitivity", UNSET)

        l9l9_header_policy = cls(
            propagation=propagation,
            retention_policy=retention_policy,
            sensitivity=sensitivity,
        )

        l9l9_header_policy.additional_properties = d
        return l9l9_header_policy

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
