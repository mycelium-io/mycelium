from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar

from attrs import define as _attrs_define
from attrs import field as _attrs_field

T = TypeVar("T", bound="SubscriptionCreate")


@_attrs_define
class SubscriptionCreate:
    """
    Attributes:
        key_pattern (str): Glob pattern for keys to watch
        subscriber (str): Agent handle subscribing
    """

    key_pattern: str
    subscriber: str
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        key_pattern = self.key_pattern

        subscriber = self.subscriber

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "key_pattern": key_pattern,
                "subscriber": subscriber,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        key_pattern = d.pop("key_pattern")

        subscriber = d.pop("subscriber")

        subscription_create = cls(
            key_pattern=key_pattern,
            subscriber=subscriber,
        )

        subscription_create.additional_properties = d
        return subscription_create

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
