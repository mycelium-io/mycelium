from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, cast

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

T = TypeVar("T", bound="L9MessageRef")


@_attrs_define
class L9MessageRef:
    """
    Attributes:
        id (str | Unset):  Default: ''.
        parents (list[str] | Unset):
        episode (None | str | Unset):
    """

    id: str | Unset = ""
    parents: list[str] | Unset = UNSET
    episode: None | str | Unset = UNSET
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        id = self.id

        parents: list[str] | Unset = UNSET
        if not isinstance(self.parents, Unset):
            parents = self.parents

        episode: None | str | Unset
        if isinstance(self.episode, Unset):
            episode = UNSET
        else:
            episode = self.episode

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update({})
        if id is not UNSET:
            field_dict["id"] = id
        if parents is not UNSET:
            field_dict["parents"] = parents
        if episode is not UNSET:
            field_dict["episode"] = episode

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        id = d.pop("id", UNSET)

        parents = cast(list[str], d.pop("parents", UNSET))

        def _parse_episode(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        episode = _parse_episode(d.pop("episode", UNSET))

        l9_message_ref = cls(
            id=id,
            parents=parents,
            episode=episode,
        )

        l9_message_ref.additional_properties = d
        return l9_message_ref

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
