from __future__ import annotations

import datetime
from collections.abc import Mapping
from typing import Any, TypeVar
from uuid import UUID

from attrs import define as _attrs_define
from attrs import field as _attrs_field
from dateutil.parser import isoparse

T = TypeVar("T", bound="SubscriptionRead")


@_attrs_define
class SubscriptionRead:
    """
    Attributes:
        id (UUID):
        room_name (str):
        subscriber (str):
        key_pattern (str):
        created_at (datetime.datetime):
    """

    id: UUID
    room_name: str
    subscriber: str
    key_pattern: str
    created_at: datetime.datetime
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        id = str(self.id)

        room_name = self.room_name

        subscriber = self.subscriber

        key_pattern = self.key_pattern

        created_at = self.created_at.isoformat()

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "id": id,
                "room_name": room_name,
                "subscriber": subscriber,
                "key_pattern": key_pattern,
                "created_at": created_at,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        id = UUID(d.pop("id"))

        room_name = d.pop("room_name")

        subscriber = d.pop("subscriber")

        key_pattern = d.pop("key_pattern")

        created_at = isoparse(d.pop("created_at"))

        subscription_read = cls(
            id=id,
            room_name=room_name,
            subscriber=subscriber,
            key_pattern=key_pattern,
            created_at=created_at,
        )

        subscription_read.additional_properties = d
        return subscription_read

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
