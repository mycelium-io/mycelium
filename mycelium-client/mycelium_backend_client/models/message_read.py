from __future__ import annotations

import datetime
from collections.abc import Mapping
from typing import Any, TypeVar, cast
from uuid import UUID

from attrs import define as _attrs_define
from attrs import field as _attrs_field
from dateutil.parser import isoparse

from ..types import UNSET, Unset

T = TypeVar("T", bound="MessageRead")


@_attrs_define
class MessageRead:
    """
    Attributes:
        id (UUID):
        room_name (str):
        sender_handle (str):
        message_type (str):
        content (str):
        created_at (datetime.datetime):
        recipient_handle (None | str | Unset):
    """

    id: UUID
    room_name: str
    sender_handle: str
    message_type: str
    content: str
    created_at: datetime.datetime
    recipient_handle: None | str | Unset = UNSET
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        id = str(self.id)

        room_name = self.room_name

        sender_handle = self.sender_handle

        message_type = self.message_type

        content = self.content

        created_at = self.created_at.isoformat()

        recipient_handle: None | str | Unset
        if isinstance(self.recipient_handle, Unset):
            recipient_handle = UNSET
        else:
            recipient_handle = self.recipient_handle

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "id": id,
                "room_name": room_name,
                "sender_handle": sender_handle,
                "message_type": message_type,
                "content": content,
                "created_at": created_at,
            }
        )
        if recipient_handle is not UNSET:
            field_dict["recipient_handle"] = recipient_handle

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        id = UUID(d.pop("id"))

        room_name = d.pop("room_name")

        sender_handle = d.pop("sender_handle")

        message_type = d.pop("message_type")

        content = d.pop("content")

        created_at = isoparse(d.pop("created_at"))

        def _parse_recipient_handle(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        recipient_handle = _parse_recipient_handle(d.pop("recipient_handle", UNSET))

        message_read = cls(
            id=id,
            room_name=room_name,
            sender_handle=sender_handle,
            message_type=message_type,
            content=content,
            created_at=created_at,
            recipient_handle=recipient_handle,
        )

        message_read.additional_properties = d
        return message_read

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
