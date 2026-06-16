from __future__ import annotations

import datetime
from collections.abc import Mapping
from typing import Any, TypeVar, cast

from attrs import define as _attrs_define
from attrs import field as _attrs_field
from dateutil.parser import isoparse

from ..types import UNSET, Unset

T = TypeVar("T", bound="RoomRead")


@_attrs_define
class RoomRead:
    """
    Attributes:
        id (int):
        name (str):
        is_public (bool):
        created_at (datetime.datetime):
        description (None | str | Unset):
        is_persistent (bool | Unset):  Default: False.
        mas_id (None | str | Unset):
        workspace_id (None | str | Unset):
    """

    id: int
    name: str
    is_public: bool
    created_at: datetime.datetime
    description: None | str | Unset = UNSET
    is_persistent: bool | Unset = False
    mas_id: None | str | Unset = UNSET
    workspace_id: None | str | Unset = UNSET
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        id = self.id

        name = self.name

        is_public = self.is_public

        created_at = self.created_at.isoformat()

        description: None | str | Unset
        if isinstance(self.description, Unset):
            description = UNSET
        else:
            description = self.description

        is_persistent = self.is_persistent

        mas_id: None | str | Unset
        if isinstance(self.mas_id, Unset):
            mas_id = UNSET
        else:
            mas_id = self.mas_id

        workspace_id: None | str | Unset
        if isinstance(self.workspace_id, Unset):
            workspace_id = UNSET
        else:
            workspace_id = self.workspace_id

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "id": id,
                "name": name,
                "is_public": is_public,
                "created_at": created_at,
            }
        )
        if description is not UNSET:
            field_dict["description"] = description
        if is_persistent is not UNSET:
            field_dict["is_persistent"] = is_persistent
        if mas_id is not UNSET:
            field_dict["mas_id"] = mas_id
        if workspace_id is not UNSET:
            field_dict["workspace_id"] = workspace_id

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        id = d.pop("id")

        name = d.pop("name")

        is_public = d.pop("is_public")

        created_at = isoparse(d.pop("created_at"))

        def _parse_description(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        description = _parse_description(d.pop("description", UNSET))

        is_persistent = d.pop("is_persistent", UNSET)

        def _parse_mas_id(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        mas_id = _parse_mas_id(d.pop("mas_id", UNSET))

        def _parse_workspace_id(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        workspace_id = _parse_workspace_id(d.pop("workspace_id", UNSET))

        room_read = cls(
            id=id,
            name=name,
            is_public=is_public,
            created_at=created_at,
            description=description,
            is_persistent=is_persistent,
            mas_id=mas_id,
            workspace_id=workspace_id,
        )

        room_read.additional_properties = d
        return room_read

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
