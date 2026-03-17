from __future__ import annotations

import datetime
from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, TypeVar, cast

from attrs import define as _attrs_define
from attrs import field as _attrs_field
from dateutil.parser import isoparse

from ..types import UNSET, Unset

if TYPE_CHECKING:
    from ..models.room_read_trigger_config_type_0 import RoomReadTriggerConfigType0


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
        coordination_state (str | Unset):  Default: 'idle'.
        mode (str | Unset):  Default: 'sync'.
        trigger_config (None | RoomReadTriggerConfigType0 | Unset):
        last_synthesis_at (datetime.datetime | None | Unset):
        is_persistent (bool | Unset):  Default: False.
    """

    id: int
    name: str
    is_public: bool
    created_at: datetime.datetime
    description: None | str | Unset = UNSET
    coordination_state: str | Unset = "idle"
    mode: str | Unset = "sync"
    trigger_config: None | RoomReadTriggerConfigType0 | Unset = UNSET
    last_synthesis_at: datetime.datetime | None | Unset = UNSET
    is_persistent: bool | Unset = False
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        from ..models.room_read_trigger_config_type_0 import RoomReadTriggerConfigType0

        id = self.id

        name = self.name

        is_public = self.is_public

        created_at = self.created_at.isoformat()

        description: None | str | Unset
        if isinstance(self.description, Unset):
            description = UNSET
        else:
            description = self.description

        coordination_state = self.coordination_state

        mode = self.mode

        trigger_config: dict[str, Any] | None | Unset
        if isinstance(self.trigger_config, Unset):
            trigger_config = UNSET
        elif isinstance(self.trigger_config, RoomReadTriggerConfigType0):
            trigger_config = self.trigger_config.to_dict()
        else:
            trigger_config = self.trigger_config

        last_synthesis_at: None | str | Unset
        if isinstance(self.last_synthesis_at, Unset):
            last_synthesis_at = UNSET
        elif isinstance(self.last_synthesis_at, datetime.datetime):
            last_synthesis_at = self.last_synthesis_at.isoformat()
        else:
            last_synthesis_at = self.last_synthesis_at

        is_persistent = self.is_persistent

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
        if coordination_state is not UNSET:
            field_dict["coordination_state"] = coordination_state
        if mode is not UNSET:
            field_dict["mode"] = mode
        if trigger_config is not UNSET:
            field_dict["trigger_config"] = trigger_config
        if last_synthesis_at is not UNSET:
            field_dict["last_synthesis_at"] = last_synthesis_at
        if is_persistent is not UNSET:
            field_dict["is_persistent"] = is_persistent

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.room_read_trigger_config_type_0 import RoomReadTriggerConfigType0

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

        coordination_state = d.pop("coordination_state", UNSET)

        mode = d.pop("mode", UNSET)

        def _parse_trigger_config(data: object) -> None | RoomReadTriggerConfigType0 | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            try:
                if not isinstance(data, dict):
                    raise TypeError()
                trigger_config_type_0 = RoomReadTriggerConfigType0.from_dict(data)

                return trigger_config_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(None | RoomReadTriggerConfigType0 | Unset, data)

        trigger_config = _parse_trigger_config(d.pop("trigger_config", UNSET))

        def _parse_last_synthesis_at(data: object) -> datetime.datetime | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            try:
                if not isinstance(data, str):
                    raise TypeError()
                last_synthesis_at_type_0 = isoparse(data)

                return last_synthesis_at_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(datetime.datetime | None | Unset, data)

        last_synthesis_at = _parse_last_synthesis_at(d.pop("last_synthesis_at", UNSET))

        is_persistent = d.pop("is_persistent", UNSET)

        room_read = cls(
            id=id,
            name=name,
            is_public=is_public,
            created_at=created_at,
            description=description,
            coordination_state=coordination_state,
            mode=mode,
            trigger_config=trigger_config,
            last_synthesis_at=last_synthesis_at,
            is_persistent=is_persistent,
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
