from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, TypeVar, cast

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

if TYPE_CHECKING:
    from ..models.l9_actor_read import L9ActorRead
    from ..models.l9_participants_read_groups_type_0 import L9ParticipantsReadGroupsType0


T = TypeVar("T", bound="L9ParticipantsRead")


@_attrs_define
class L9ParticipantsRead:
    """
    Attributes:
        actors (list[L9ActorRead] | Unset):
        groups (L9ParticipantsReadGroupsType0 | None | Unset):
    """

    actors: list[L9ActorRead] | Unset = UNSET
    groups: L9ParticipantsReadGroupsType0 | None | Unset = UNSET
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        from ..models.l9_participants_read_groups_type_0 import L9ParticipantsReadGroupsType0

        actors: list[dict[str, Any]] | Unset = UNSET
        if not isinstance(self.actors, Unset):
            actors = []
            for actors_item_data in self.actors:
                actors_item = actors_item_data.to_dict()
                actors.append(actors_item)

        groups: dict[str, Any] | None | Unset
        if isinstance(self.groups, Unset):
            groups = UNSET
        elif isinstance(self.groups, L9ParticipantsReadGroupsType0):
            groups = self.groups.to_dict()
        else:
            groups = self.groups

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
        from ..models.l9_actor_read import L9ActorRead
        from ..models.l9_participants_read_groups_type_0 import L9ParticipantsReadGroupsType0

        d = dict(src_dict)
        _actors = d.pop("actors", UNSET)
        actors: list[L9ActorRead] | Unset = UNSET
        if _actors is not UNSET:
            actors = []
            for actors_item_data in _actors:
                actors_item = L9ActorRead.from_dict(actors_item_data)

                actors.append(actors_item)

        def _parse_groups(data: object) -> L9ParticipantsReadGroupsType0 | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            try:
                if not isinstance(data, dict):
                    raise TypeError()
                groups_type_0 = L9ParticipantsReadGroupsType0.from_dict(data)

                return groups_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(L9ParticipantsReadGroupsType0 | None | Unset, data)

        groups = _parse_groups(d.pop("groups", UNSET))

        l9_participants_read = cls(
            actors=actors,
            groups=groups,
        )

        l9_participants_read.additional_properties = d
        return l9_participants_read

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
