from __future__ import annotations

import datetime
from collections.abc import Mapping
from typing import Any, TypeVar, cast
from uuid import UUID

from attrs import define as _attrs_define
from attrs import field as _attrs_field
from dateutil.parser import isoparse

from ..types import UNSET, Unset

T = TypeVar("T", bound="CoordinationSessionRead")


@_attrs_define
class CoordinationSessionRead:
    """
    Attributes:
        created_at (datetime.datetime):
        display_name (str):
        id (UUID):
        parent_room_name (str):
        short_id (str):
        state (str):
        join_window_ends_at (datetime.datetime | None | Unset):
        mas_id (None | str | Unset):
        workspace_id (None | str | Unset):
    """

    created_at: datetime.datetime
    display_name: str
    id: UUID
    parent_room_name: str
    short_id: str
    state: str
    join_window_ends_at: datetime.datetime | None | Unset = UNSET
    mas_id: None | str | Unset = UNSET
    workspace_id: None | str | Unset = UNSET
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        created_at = self.created_at.isoformat()

        display_name = self.display_name

        id = str(self.id)

        parent_room_name = self.parent_room_name

        short_id = self.short_id

        state = self.state

        join_window_ends_at: None | str | Unset
        if isinstance(self.join_window_ends_at, Unset):
            join_window_ends_at = UNSET
        elif isinstance(self.join_window_ends_at, datetime.datetime):
            join_window_ends_at = self.join_window_ends_at.isoformat()
        else:
            join_window_ends_at = self.join_window_ends_at

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
                "created_at": created_at,
                "display_name": display_name,
                "id": id,
                "parent_room_name": parent_room_name,
                "short_id": short_id,
                "state": state,
            }
        )
        if join_window_ends_at is not UNSET:
            field_dict["join_window_ends_at"] = join_window_ends_at
        if mas_id is not UNSET:
            field_dict["mas_id"] = mas_id
        if workspace_id is not UNSET:
            field_dict["workspace_id"] = workspace_id

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        created_at = isoparse(d.pop("created_at"))

        display_name = d.pop("display_name")

        id = UUID(d.pop("id"))

        parent_room_name = d.pop("parent_room_name")

        short_id = d.pop("short_id")

        state = d.pop("state")

        def _parse_join_window_ends_at(data: object) -> datetime.datetime | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            try:
                if not isinstance(data, str):
                    raise TypeError()
                join_window_ends_at_type_0 = isoparse(data)

                return join_window_ends_at_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(datetime.datetime | None | Unset, data)

        join_window_ends_at = _parse_join_window_ends_at(d.pop("join_window_ends_at", UNSET))

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

        coordination_session_read = cls(
            created_at=created_at,
            display_name=display_name,
            id=id,
            parent_room_name=parent_room_name,
            short_id=short_id,
            state=state,
            join_window_ends_at=join_window_ends_at,
            mas_id=mas_id,
            workspace_id=workspace_id,
        )

        coordination_session_read.additional_properties = d
        return coordination_session_read

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
