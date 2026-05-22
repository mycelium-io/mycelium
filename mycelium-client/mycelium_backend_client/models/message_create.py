from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, cast

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

T = TypeVar("T", bound="MessageCreate")


@_attrs_define
class MessageCreate:
    """
    Attributes:
        content (str):
        message_type (str): Type: announce, direct, broadcast, or delegate
        sender_handle (str): Sender handle (e.g., 'alpha#a8f3')
        recipient_handle (None | str | Unset): Recipient handle for direct messages; omit for broadcast
    """

    content: str
    message_type: str
    sender_handle: str
    recipient_handle: None | str | Unset = UNSET
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        content = self.content

        message_type = self.message_type

        sender_handle = self.sender_handle

        recipient_handle: None | str | Unset
        if isinstance(self.recipient_handle, Unset):
            recipient_handle = UNSET
        else:
            recipient_handle = self.recipient_handle

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "content": content,
                "message_type": message_type,
                "sender_handle": sender_handle,
            }
        )
        if recipient_handle is not UNSET:
            field_dict["recipient_handle"] = recipient_handle

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        content = d.pop("content")

        message_type = d.pop("message_type")

        sender_handle = d.pop("sender_handle")

        def _parse_recipient_handle(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        recipient_handle = _parse_recipient_handle(d.pop("recipient_handle", UNSET))

        message_create = cls(
            content=content,
            message_type=message_type,
            sender_handle=sender_handle,
            recipient_handle=recipient_handle,
        )

        message_create.additional_properties = d
        return message_create

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
