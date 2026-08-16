from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, cast

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

T = TypeVar("T", bound="UserCreate")


@_attrs_define
class UserCreate:
    """
    Attributes:
        handle (str):
        display_name (str | Unset):  Default: ''.
        teams (list[str] | Unset):
        notify (None | str | Unset):
    """

    handle: str
    display_name: str | Unset = ""
    teams: list[str] | Unset = UNSET
    notify: None | str | Unset = UNSET
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        handle = self.handle

        display_name = self.display_name

        teams: list[str] | Unset = UNSET
        if not isinstance(self.teams, Unset):
            teams = self.teams

        notify: None | str | Unset
        if isinstance(self.notify, Unset):
            notify = UNSET
        else:
            notify = self.notify

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "handle": handle,
            }
        )
        if display_name is not UNSET:
            field_dict["display_name"] = display_name
        if teams is not UNSET:
            field_dict["teams"] = teams
        if notify is not UNSET:
            field_dict["notify"] = notify

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        handle = d.pop("handle")

        display_name = d.pop("display_name", UNSET)

        teams = cast(list[str], d.pop("teams", UNSET))

        def _parse_notify(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        notify = _parse_notify(d.pop("notify", UNSET))

        user_create = cls(
            handle=handle,
            display_name=display_name,
            teams=teams,
            notify=notify,
        )

        user_create.additional_properties = d
        return user_create

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
