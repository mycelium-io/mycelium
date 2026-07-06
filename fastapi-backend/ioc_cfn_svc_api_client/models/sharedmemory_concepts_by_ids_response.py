from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, TypeVar

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

if TYPE_CHECKING:
    from ..models.sharedmemory_graph_concept import SharedmemoryGraphConcept


T = TypeVar("T", bound="SharedmemoryConceptsByIdsResponse")


@_attrs_define
class SharedmemoryConceptsByIdsResponse:
    """
    Attributes:
        concepts (list[SharedmemoryGraphConcept] | Unset):
    """

    concepts: list[SharedmemoryGraphConcept] | Unset = UNSET
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        concepts: list[dict[str, Any]] | Unset = UNSET
        if not isinstance(self.concepts, Unset):
            concepts = []
            for concepts_item_data in self.concepts:
                concepts_item = concepts_item_data.to_dict()
                concepts.append(concepts_item)

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update({})
        if concepts is not UNSET:
            field_dict["concepts"] = concepts

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.sharedmemory_graph_concept import SharedmemoryGraphConcept

        d = dict(src_dict)
        _concepts = d.pop("concepts", UNSET)
        concepts: list[SharedmemoryGraphConcept] | Unset = UNSET
        if _concepts is not UNSET:
            concepts = []
            for concepts_item_data in _concepts:
                concepts_item = SharedmemoryGraphConcept.from_dict(concepts_item_data)

                concepts.append(concepts_item)

        sharedmemory_concepts_by_ids_response = cls(
            concepts=concepts,
        )

        sharedmemory_concepts_by_ids_response.additional_properties = d
        return sharedmemory_concepts_by_ids_response

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
