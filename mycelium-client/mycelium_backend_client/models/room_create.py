from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, TypeVar, cast

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

if TYPE_CHECKING:
    from ..models.room_create_trigger_config_type_0 import RoomCreateTriggerConfigType0


T = TypeVar("T", bound="RoomCreate")


@_attrs_define
class RoomCreate:
    """
    Attributes:
        name (str):
        description (None | str | Unset):
        is_public (bool | Unset):  Default: True.
        trigger_config (None | RoomCreateTriggerConfigType0 | Unset):
    """

    name: str
    description: None | str | Unset = UNSET
    is_public: bool | Unset = True
    trigger_config: None | RoomCreateTriggerConfigType0 | Unset = UNSET
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        from ..models.room_create_trigger_config_type_0 import RoomCreateTriggerConfigType0

        name = self.name

        description: None | str | Unset
        if isinstance(self.description, Unset):
            description = UNSET
        else:
            description = self.description

        is_public = self.is_public

        trigger_config: dict[str, Any] | None | Unset
        if isinstance(self.trigger_config, Unset):
            trigger_config = UNSET
        elif isinstance(self.trigger_config, RoomCreateTriggerConfigType0):
            trigger_config = self.trigger_config.to_dict()
        else:
            trigger_config = self.trigger_config

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "name": name,
            }
        )
        if description is not UNSET:
            field_dict["description"] = description
        if is_public is not UNSET:
            field_dict["is_public"] = is_public
        if trigger_config is not UNSET:
            field_dict["trigger_config"] = trigger_config

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.room_create_trigger_config_type_0 import RoomCreateTriggerConfigType0

        d = dict(src_dict)
        name = d.pop("name")

        def _parse_description(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        description = _parse_description(d.pop("description", UNSET))

        is_public = d.pop("is_public", UNSET)

        def _parse_trigger_config(data: object) -> None | RoomCreateTriggerConfigType0 | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            try:
                if not isinstance(data, dict):
                    raise TypeError()
                trigger_config_type_0 = RoomCreateTriggerConfigType0.from_dict(data)

                return trigger_config_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(None | RoomCreateTriggerConfigType0 | Unset, data)

        trigger_config = _parse_trigger_config(d.pop("trigger_config", UNSET))

        room_create = cls(
            name=name,
            description=description,
            is_public=is_public,
            trigger_config=trigger_config,
        )

        room_create.additional_properties = d
        return room_create

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
