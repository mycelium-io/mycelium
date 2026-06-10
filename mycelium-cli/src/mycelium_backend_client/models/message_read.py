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
        content (str):
        created_at (datetime.datetime):
        id (UUID):
        message_type (str):
        sender_handle (str):
        coordination_session_id (None | Unset | UUID):
        recipient_handle (None | str | Unset):
        room_name (None | str | Unset):
    """

    content: str
    created_at: datetime.datetime
    id: UUID
    message_type: str
    sender_handle: str
    coordination_session_id: None | Unset | UUID = UNSET
    recipient_handle: None | str | Unset = UNSET
    room_name: None | str | Unset = UNSET
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        content = self.content

        created_at = self.created_at.isoformat()

        id = str(self.id)

        message_type = self.message_type

        sender_handle = self.sender_handle

        coordination_session_id: None | str | Unset
        if isinstance(self.coordination_session_id, Unset):
            coordination_session_id = UNSET
        elif isinstance(self.coordination_session_id, UUID):
            coordination_session_id = str(self.coordination_session_id)
        else:
            coordination_session_id = self.coordination_session_id

        recipient_handle: None | str | Unset
        if isinstance(self.recipient_handle, Unset):
            recipient_handle = UNSET
        else:
            recipient_handle = self.recipient_handle

        room_name: None | str | Unset
        if isinstance(self.room_name, Unset):
            room_name = UNSET
        else:
            room_name = self.room_name

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "content": content,
                "created_at": created_at,
                "id": id,
                "message_type": message_type,
                "sender_handle": sender_handle,
            }
        )
        if coordination_session_id is not UNSET:
            field_dict["coordination_session_id"] = coordination_session_id
        if recipient_handle is not UNSET:
            field_dict["recipient_handle"] = recipient_handle
        if room_name is not UNSET:
            field_dict["room_name"] = room_name

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        content = d.pop("content")

        created_at = isoparse(d.pop("created_at"))

        id = UUID(d.pop("id"))

        message_type = d.pop("message_type")

        sender_handle = d.pop("sender_handle")

        def _parse_coordination_session_id(data: object) -> None | Unset | UUID:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            try:
                if not isinstance(data, str):
                    raise TypeError()
                coordination_session_id_type_0 = UUID(data)

                return coordination_session_id_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(None | Unset | UUID, data)

        coordination_session_id = _parse_coordination_session_id(
            d.pop("coordination_session_id", UNSET)
        )

        def _parse_recipient_handle(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        recipient_handle = _parse_recipient_handle(d.pop("recipient_handle", UNSET))

        def _parse_room_name(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        room_name = _parse_room_name(d.pop("room_name", UNSET))

        message_read = cls(
            content=content,
            created_at=created_at,
            id=id,
            message_type=message_type,
            sender_handle=sender_handle,
            coordination_session_id=coordination_session_id,
            recipient_handle=recipient_handle,
            room_name=room_name,
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
