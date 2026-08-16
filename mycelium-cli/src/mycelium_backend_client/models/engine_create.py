from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, cast

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

T = TypeVar("T", bound="EngineCreate")


@_attrs_define
class EngineCreate:
    """Request body to invite an engine into a room.

    Attributes:
        handle (str):
        kind (str | Unset): Which cognition engine to run. Default: 'aligner'.
        description (str | Unset):  Default: ''.
        allow_from (list[str] | Unset): Sender handles allowed to summon (empty = anyone).
        owner (None | str | Unset):
        team (None | str | Unset):
        created_by (None | str | Unset): Who registered the engine; defaults to the web UI.
    """

    handle: str
    kind: str | Unset = "aligner"
    description: str | Unset = ""
    allow_from: list[str] | Unset = UNSET
    owner: None | str | Unset = UNSET
    team: None | str | Unset = UNSET
    created_by: None | str | Unset = UNSET
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        handle = self.handle

        kind = self.kind

        description = self.description

        allow_from: list[str] | Unset = UNSET
        if not isinstance(self.allow_from, Unset):
            allow_from = self.allow_from

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

        created_by: None | str | Unset
        if isinstance(self.created_by, Unset):
            created_by = UNSET
        else:
            created_by = self.created_by

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "handle": handle,
            }
        )
        if kind is not UNSET:
            field_dict["kind"] = kind
        if description is not UNSET:
            field_dict["description"] = description
        if allow_from is not UNSET:
            field_dict["allow_from"] = allow_from
        if owner is not UNSET:
            field_dict["owner"] = owner
        if team is not UNSET:
            field_dict["team"] = team
        if created_by is not UNSET:
            field_dict["created_by"] = created_by

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        handle = d.pop("handle")

        kind = d.pop("kind", UNSET)

        description = d.pop("description", UNSET)

        allow_from = cast(list[str], d.pop("allow_from", UNSET))

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

        def _parse_created_by(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        created_by = _parse_created_by(d.pop("created_by", UNSET))

        engine_create = cls(
            handle=handle,
            kind=kind,
            description=description,
            allow_from=allow_from,
            owner=owner,
            team=team,
            created_by=created_by,
        )

        engine_create.additional_properties = d
        return engine_create

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
