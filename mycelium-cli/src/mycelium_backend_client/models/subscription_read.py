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
        created_at (datetime.datetime):
        id (UUID):
        key_pattern (str):
        room_name (str):
        subscriber (str):
    """

    created_at: datetime.datetime
    id: UUID
    key_pattern: str
    room_name: str
    subscriber: str
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        created_at = self.created_at.isoformat()

        id = str(self.id)

        key_pattern = self.key_pattern

        room_name = self.room_name

        subscriber = self.subscriber

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "created_at": created_at,
                "id": id,
                "key_pattern": key_pattern,
                "room_name": room_name,
                "subscriber": subscriber,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        created_at = isoparse(d.pop("created_at"))

        id = UUID(d.pop("id"))

        key_pattern = d.pop("key_pattern")

        room_name = d.pop("room_name")

        subscriber = d.pop("subscriber")

        subscription_read = cls(
            created_at=created_at,
            id=id,
            key_pattern=key_pattern,
            room_name=room_name,
            subscriber=subscriber,
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
