from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, cast

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

T = TypeVar("T", bound="TeamRead")


@_attrs_define
class TeamRead:
    """A team, rolled up from the agents fielded under it and its member users.

    Attributes:
        team (str):
        members (list[str] | Unset):
        agent_count (int | Unset):  Default: 0.
    """

    team: str
    members: list[str] | Unset = UNSET
    agent_count: int | Unset = 0
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        team = self.team

        members: list[str] | Unset = UNSET
        if not isinstance(self.members, Unset):
            members = self.members

        agent_count = self.agent_count

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "team": team,
            }
        )
        if members is not UNSET:
            field_dict["members"] = members
        if agent_count is not UNSET:
            field_dict["agent_count"] = agent_count

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        team = d.pop("team")

        members = cast(list[str], d.pop("members", UNSET))

        agent_count = d.pop("agent_count", UNSET)

        team_read = cls(
            team=team,
            members=members,
            agent_count=agent_count,
        )

        team_read.additional_properties = d
        return team_read

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
