from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, TypeVar

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

if TYPE_CHECKING:
    from ..models.sharedmemory_query_concept import SharedmemoryQueryConcept
    from ..models.sharedmemory_query_relation import SharedmemoryQueryRelation


T = TypeVar("T", bound="SharedmemoryQueryResponseRecord")


@_attrs_define
class SharedmemoryQueryResponseRecord:
    """
    Attributes:
        concepts (list[SharedmemoryQueryConcept] | Unset):
        relationships (list[SharedmemoryQueryRelation] | Unset):
    """

    concepts: list[SharedmemoryQueryConcept] | Unset = UNSET
    relationships: list[SharedmemoryQueryRelation] | Unset = UNSET
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        concepts: list[dict[str, Any]] | Unset = UNSET
        if not isinstance(self.concepts, Unset):
            concepts = []
            for concepts_item_data in self.concepts:
                concepts_item = concepts_item_data.to_dict()
                concepts.append(concepts_item)

        relationships: list[dict[str, Any]] | Unset = UNSET
        if not isinstance(self.relationships, Unset):
            relationships = []
            for relationships_item_data in self.relationships:
                relationships_item = relationships_item_data.to_dict()
                relationships.append(relationships_item)

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update({})
        if concepts is not UNSET:
            field_dict["concepts"] = concepts
        if relationships is not UNSET:
            field_dict["relationships"] = relationships

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.sharedmemory_query_concept import SharedmemoryQueryConcept
        from ..models.sharedmemory_query_relation import SharedmemoryQueryRelation

        d = dict(src_dict)
        _concepts = d.pop("concepts", UNSET)
        concepts: list[SharedmemoryQueryConcept] | Unset = UNSET
        if _concepts is not UNSET:
            concepts = []
            for concepts_item_data in _concepts:
                concepts_item = SharedmemoryQueryConcept.from_dict(concepts_item_data)

                concepts.append(concepts_item)

        _relationships = d.pop("relationships", UNSET)
        relationships: list[SharedmemoryQueryRelation] | Unset = UNSET
        if _relationships is not UNSET:
            relationships = []
            for relationships_item_data in _relationships:
                relationships_item = SharedmemoryQueryRelation.from_dict(relationships_item_data)

                relationships.append(relationships_item)

        sharedmemory_query_response_record = cls(
            concepts=concepts,
            relationships=relationships,
        )

        sharedmemory_query_response_record.additional_properties = d
        return sharedmemory_query_response_record

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
