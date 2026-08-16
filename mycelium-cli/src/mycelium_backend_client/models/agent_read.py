from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, cast

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

T = TypeVar("T", bound="AgentRead")


@_attrs_define
class AgentRead:
    """Structured view of an agent's manifest, as returned by GET /rooms/{room}/agents.

    Attributes:
        handle (str):
        adapter (str):
        kind (None | str | Unset):
        description (str | Unset):  Default: ''.
        cwd (None | str | Unset):
        owner (None | str | Unset):
        team (None | str | Unset):
        allow_from (list[str] | Unset):
    """

    handle: str
    adapter: str
    kind: None | str | Unset = UNSET
    description: str | Unset = ""
    cwd: None | str | Unset = UNSET
    owner: None | str | Unset = UNSET
    team: None | str | Unset = UNSET
    allow_from: list[str] | Unset = UNSET
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        handle = self.handle

        adapter = self.adapter

        kind: None | str | Unset
        if isinstance(self.kind, Unset):
            kind = UNSET
        else:
            kind = self.kind

        description = self.description

        cwd: None | str | Unset
        if isinstance(self.cwd, Unset):
            cwd = UNSET
        else:
            cwd = self.cwd

        owner: None | str | Unset
        if isinstance(self.owner, Unset):
            owner = UNSET
        else:
            owner = self.owner

        team: None | str | Unset
        if isinstance(self.team, Unset):
            team = UNSET
        else:
            team = self.team

        allow_from: list[str] | Unset = UNSET
        if not isinstance(self.allow_from, Unset):
            allow_from = self.allow_from

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "handle": handle,
                "adapter": adapter,
            }
        )
        if kind is not UNSET:
            field_dict["kind"] = kind
        if description is not UNSET:
            field_dict["description"] = description
        if cwd is not UNSET:
            field_dict["cwd"] = cwd
        if owner is not UNSET:
            field_dict["owner"] = owner
        if team is not UNSET:
            field_dict["team"] = team
        if allow_from is not UNSET:
            field_dict["allow_from"] = allow_from

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        handle = d.pop("handle")

        adapter = d.pop("adapter")

        def _parse_kind(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        kind = _parse_kind(d.pop("kind", UNSET))

        description = d.pop("description", UNSET)

        def _parse_cwd(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        cwd = _parse_cwd(d.pop("cwd", UNSET))

        def _parse_owner(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        owner = _parse_owner(d.pop("owner", UNSET))

        def _parse_team(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        team = _parse_team(d.pop("team", UNSET))

        allow_from = cast(list[str], d.pop("allow_from", UNSET))

        agent_read = cls(
            handle=handle,
            adapter=adapter,
            kind=kind,
            description=description,
            cwd=cwd,
            owner=owner,
            team=team,
            allow_from=allow_from,
        )

        agent_read.additional_properties = d
        return agent_read

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
