from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

T = TypeVar("T", bound="SharedmemoryPathEdge")


@_attrs_define
class SharedmemoryPathEdge:
    """
    Attributes:
        from_id (str | Unset):
        from_name (str | Unset):
        relation (str | Unset):
        to_id (str | Unset):
        to_name (str | Unset):
    """

    from_id: str | Unset = UNSET
    from_name: str | Unset = UNSET
    relation: str | Unset = UNSET
    to_id: str | Unset = UNSET
    to_name: str | Unset = UNSET
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        from_id = self.from_id

        from_name = self.from_name

        relation = self.relation

        to_id = self.to_id

        to_name = self.to_name

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update({})
        if from_id is not UNSET:
            field_dict["from_id"] = from_id
        if from_name is not UNSET:
            field_dict["from_name"] = from_name
        if relation is not UNSET:
            field_dict["relation"] = relation
        if to_id is not UNSET:
            field_dict["to_id"] = to_id
        if to_name is not UNSET:
            field_dict["to_name"] = to_name

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        from_id = d.pop("from_id", UNSET)

        from_name = d.pop("from_name", UNSET)

        relation = d.pop("relation", UNSET)

        to_id = d.pop("to_id", UNSET)

        to_name = d.pop("to_name", UNSET)

        sharedmemory_path_edge = cls(
            from_id=from_id,
            from_name=from_name,
            relation=relation,
            to_id=to_id,
            to_name=to_name,
        )

        sharedmemory_path_edge.additional_properties = d
        return sharedmemory_path_edge

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
