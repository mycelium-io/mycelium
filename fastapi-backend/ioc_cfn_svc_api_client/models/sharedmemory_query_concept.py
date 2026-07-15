from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, TypeVar, cast

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

if TYPE_CHECKING:
    from ..models.sharedmemory_query_concept_attributes import SharedmemoryQueryConceptAttributes


T = TypeVar("T", bound="SharedmemoryQueryConcept")


@_attrs_define
class SharedmemoryQueryConcept:
    """
    Attributes:
        attributes (SharedmemoryQueryConceptAttributes | Unset):
        description (str | Unset):
        id (str | Unset):
        name (str | Unset):
        tags (list[str] | Unset):
    """

    attributes: SharedmemoryQueryConceptAttributes | Unset = UNSET
    description: str | Unset = UNSET
    id: str | Unset = UNSET
    name: str | Unset = UNSET
    tags: list[str] | Unset = UNSET
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        attributes: dict[str, Any] | Unset = UNSET
        if not isinstance(self.attributes, Unset):
            attributes = self.attributes.to_dict()

        description = self.description

        id = self.id

        name = self.name

        tags: list[str] | Unset = UNSET
        if not isinstance(self.tags, Unset):
            tags = self.tags

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update({})
        if attributes is not UNSET:
            field_dict["attributes"] = attributes
        if description is not UNSET:
            field_dict["description"] = description
        if id is not UNSET:
            field_dict["id"] = id
        if name is not UNSET:
            field_dict["name"] = name
        if tags is not UNSET:
            field_dict["tags"] = tags

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.sharedmemory_query_concept_attributes import (
            SharedmemoryQueryConceptAttributes,
        )

        d = dict(src_dict)
        _attributes = d.pop("attributes", UNSET)
        attributes: SharedmemoryQueryConceptAttributes | Unset
        if isinstance(_attributes, Unset):
            attributes = UNSET
        else:
            attributes = SharedmemoryQueryConceptAttributes.from_dict(_attributes)

        description = d.pop("description", UNSET)

        id = d.pop("id", UNSET)

        name = d.pop("name", UNSET)

        tags = cast(list[str], d.pop("tags", UNSET))

        sharedmemory_query_concept = cls(
            attributes=attributes,
            description=description,
            id=id,
            name=name,
            tags=tags,
        )

        sharedmemory_query_concept.additional_properties = d
        return sharedmemory_query_concept

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
