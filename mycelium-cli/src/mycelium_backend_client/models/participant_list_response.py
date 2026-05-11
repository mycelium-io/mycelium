from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, TypeVar

from attrs import define as _attrs_define
from attrs import field as _attrs_field

if TYPE_CHECKING:
    from ..models.participant_read import ParticipantRead


T = TypeVar("T", bound="ParticipantListResponse")


@_attrs_define
class ParticipantListResponse:
    """
    Attributes:
        participants (list[ParticipantRead]):
        total (int):
    """

    participants: list[ParticipantRead]
    total: int
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        participants = []
        for participants_item_data in self.participants:
            participants_item = participants_item_data.to_dict()
            participants.append(participants_item)

        total = self.total

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "participants": participants,
                "total": total,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.participant_read import ParticipantRead

        d = dict(src_dict)
        participants = []
        _participants = d.pop("participants")
        for participants_item_data in _participants:
            participants_item = ParticipantRead.from_dict(participants_item_data)

            participants.append(participants_item)

        total = d.pop("total")

        participant_list_response = cls(
            participants=participants,
            total=total,
        )

        participant_list_response.additional_properties = d
        return participant_list_response

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
