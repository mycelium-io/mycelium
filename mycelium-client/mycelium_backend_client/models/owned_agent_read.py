from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, cast

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

T = TypeVar("T", bound="OwnedAgentRead")


@_attrs_define
class OwnedAgentRead:
    """One agent bound to a principal, with its room.

    Attributes:
        room (str):
        handle (str):
        adapter (str):
        team (None | str | Unset):
    """

    room: str
    handle: str
    adapter: str
    team: None | str | Unset = UNSET
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        room = self.room

        handle = self.handle

        adapter = self.adapter

        team: None | str | Unset
        if isinstance(self.team, Unset):
            team = UNSET
        else:
            team = self.team

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "room": room,
                "handle": handle,
                "adapter": adapter,
            }
        )
        if team is not UNSET:
            field_dict["team"] = team

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        room = d.pop("room")

        handle = d.pop("handle")

        adapter = d.pop("adapter")

        def _parse_team(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        team = _parse_team(d.pop("team", UNSET))

        owned_agent_read = cls(
            room=room,
            handle=handle,
            adapter=adapter,
            team=team,
        )

        owned_agent_read.additional_properties = d
        return owned_agent_read

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
