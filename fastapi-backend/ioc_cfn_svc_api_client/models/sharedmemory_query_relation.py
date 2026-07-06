from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, TypeVar, cast

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

if TYPE_CHECKING:
    from ..models.sharedmemory_query_relation_attributes import SharedmemoryQueryRelationAttributes


T = TypeVar("T", bound="SharedmemoryQueryRelation")


@_attrs_define
class SharedmemoryQueryRelation:
    """
    Attributes:
        attributes (SharedmemoryQueryRelationAttributes | Unset):
        id (str | Unset):
        node_ids (list[str] | Unset):
        relation (str | Unset):
    """

    attributes: SharedmemoryQueryRelationAttributes | Unset = UNSET
    id: str | Unset = UNSET
    node_ids: list[str] | Unset = UNSET
    relation: str | Unset = UNSET
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        attributes: dict[str, Any] | Unset = UNSET
        if not isinstance(self.attributes, Unset):
            attributes = self.attributes.to_dict()

        id = self.id

        node_ids: list[str] | Unset = UNSET
        if not isinstance(self.node_ids, Unset):
            node_ids = self.node_ids

        relation = self.relation

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update({})
        if attributes is not UNSET:
            field_dict["attributes"] = attributes
        if id is not UNSET:
            field_dict["id"] = id
        if node_ids is not UNSET:
            field_dict["node_ids"] = node_ids
        if relation is not UNSET:
            field_dict["relation"] = relation

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.sharedmemory_query_relation_attributes import (
            SharedmemoryQueryRelationAttributes,
        )

        d = dict(src_dict)
        _attributes = d.pop("attributes", UNSET)
        attributes: SharedmemoryQueryRelationAttributes | Unset
        if isinstance(_attributes, Unset):
            attributes = UNSET
        else:
            attributes = SharedmemoryQueryRelationAttributes.from_dict(_attributes)

        id = d.pop("id", UNSET)

        node_ids = cast(list[str], d.pop("node_ids", UNSET))

        relation = d.pop("relation", UNSET)

        sharedmemory_query_relation = cls(
            attributes=attributes,
            id=id,
            node_ids=node_ids,
            relation=relation,
        )

        sharedmemory_query_relation.additional_properties = d
        return sharedmemory_query_relation

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
