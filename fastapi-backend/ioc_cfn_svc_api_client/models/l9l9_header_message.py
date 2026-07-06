from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, cast

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

T = TypeVar("T", bound="L9L9HeaderMessage")


@_attrs_define
class L9L9HeaderMessage:
    """
    Attributes:
        episode (str | Unset): Episode corresponds to the JSON schema field "episode".
        id (str | Unset): ID corresponds to the JSON schema field "id".
        parents (list[str] | Unset): Ordered list of parent message IDs. Empty list for root messages.
    """

    episode: str | Unset = UNSET
    id: str | Unset = UNSET
    parents: list[str] | Unset = UNSET
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        episode = self.episode

        id = self.id

        parents: list[str] | Unset = UNSET
        if not isinstance(self.parents, Unset):
            parents = self.parents

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update({})
        if episode is not UNSET:
            field_dict["episode"] = episode
        if id is not UNSET:
            field_dict["id"] = id
        if parents is not UNSET:
            field_dict["parents"] = parents

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        episode = d.pop("episode", UNSET)

        id = d.pop("id", UNSET)

        parents = cast(list[str], d.pop("parents", UNSET))

        l9l9_header_message = cls(
            episode=episode,
            id=id,
            parents=parents,
        )

        l9l9_header_message.additional_properties = d
        return l9l9_header_message

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
