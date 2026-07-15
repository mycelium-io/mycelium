from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, TypeVar

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

if TYPE_CHECKING:
    from ..models.l9_actor import L9Actor
    from ..models.l9_participant_set_groups import L9ParticipantSetGroups


T = TypeVar("T", bound="L9ParticipantSet")


@_attrs_define
class L9ParticipantSet:
    """
    Attributes:
        actors (list[L9Actor] | Unset): Actors corresponds to the JSON schema field "actors".
        groups (L9ParticipantSetGroups | Unset):
    """

    actors: list[L9Actor] | Unset = UNSET
    groups: L9ParticipantSetGroups | Unset = UNSET
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        actors: list[dict[str, Any]] | Unset = UNSET
        if not isinstance(self.actors, Unset):
            actors = []
            for actors_item_data in self.actors:
                actors_item = actors_item_data.to_dict()
                actors.append(actors_item)

        groups: dict[str, Any] | Unset = UNSET
        if not isinstance(self.groups, Unset):
            groups = self.groups.to_dict()

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update({})
        if actors is not UNSET:
            field_dict["actors"] = actors
        if groups is not UNSET:
            field_dict["groups"] = groups

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.l9_actor import L9Actor
        from ..models.l9_participant_set_groups import L9ParticipantSetGroups

        d = dict(src_dict)
        _actors = d.pop("actors", UNSET)
        actors: list[L9Actor] | Unset = UNSET
        if _actors is not UNSET:
            actors = []
            for actors_item_data in _actors:
                actors_item = L9Actor.from_dict(actors_item_data)

                actors.append(actors_item)

        _groups = d.pop("groups", UNSET)
        groups: L9ParticipantSetGroups | Unset
        if isinstance(_groups, Unset):
            groups = UNSET
        else:
            groups = L9ParticipantSetGroups.from_dict(_groups)

        l9_participant_set = cls(
            actors=actors,
            groups=groups,
        )

        l9_participant_set.additional_properties = d
        return l9_participant_set

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
