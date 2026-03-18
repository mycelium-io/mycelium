from __future__ import annotations

import datetime
from collections.abc import Mapping
from typing import Any, TypeVar, cast
from uuid import UUID

from attrs import define as _attrs_define
from attrs import field as _attrs_field
from dateutil.parser import isoparse

from ..types import UNSET, Unset

T = TypeVar("T", bound="SessionRead")


@_attrs_define
class SessionRead:
    """
    Attributes:
        id (UUID):
        room_name (str):
        agent_handle (str):
        joined_at (datetime.datetime):
        last_seen (datetime.datetime | None | Unset):
    """

    id: UUID
    room_name: str
    agent_handle: str
    joined_at: datetime.datetime
    last_seen: datetime.datetime | None | Unset = UNSET
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        id = str(self.id)

        room_name = self.room_name

        agent_handle = self.agent_handle

        joined_at = self.joined_at.isoformat()

        last_seen: None | str | Unset
        if isinstance(self.last_seen, Unset):
            last_seen = UNSET
        elif isinstance(self.last_seen, datetime.datetime):
            last_seen = self.last_seen.isoformat()
        else:
            last_seen = self.last_seen

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "id": id,
                "room_name": room_name,
                "agent_handle": agent_handle,
                "joined_at": joined_at,
            }
        )
        if last_seen is not UNSET:
            field_dict["last_seen"] = last_seen

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        id = UUID(d.pop("id"))

        room_name = d.pop("room_name")

        agent_handle = d.pop("agent_handle")

        joined_at = isoparse(d.pop("joined_at"))

        def _parse_last_seen(data: object) -> datetime.datetime | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            try:
                if not isinstance(data, str):
                    raise TypeError()
                last_seen_type_0 = isoparse(data)

                return last_seen_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(datetime.datetime | None | Unset, data)

        last_seen = _parse_last_seen(d.pop("last_seen", UNSET))

        session_read = cls(
            id=id,
            room_name=room_name,
            agent_handle=agent_handle,
            joined_at=joined_at,
            last_seen=last_seen,
        )

        session_read.additional_properties = d
        return session_read

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
