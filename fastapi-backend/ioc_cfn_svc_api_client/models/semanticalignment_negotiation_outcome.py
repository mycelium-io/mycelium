from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

T = TypeVar("T", bound="SemanticalignmentNegotiationOutcome")


@_attrs_define
class SemanticalignmentNegotiationOutcome:
    """
    Attributes:
        chosen_option (str | Unset):
        issue_id (str | Unset):
    """

    chosen_option: str | Unset = UNSET
    issue_id: str | Unset = UNSET
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        chosen_option = self.chosen_option

        issue_id = self.issue_id

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update({})
        if chosen_option is not UNSET:
            field_dict["chosen_option"] = chosen_option
        if issue_id is not UNSET:
            field_dict["issue_id"] = issue_id

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        chosen_option = d.pop("chosen_option", UNSET)

        issue_id = d.pop("issue_id", UNSET)

        semanticalignment_negotiation_outcome = cls(
            chosen_option=chosen_option,
            issue_id=issue_id,
        )

        semanticalignment_negotiation_outcome.additional_properties = d
        return semanticalignment_negotiation_outcome

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
