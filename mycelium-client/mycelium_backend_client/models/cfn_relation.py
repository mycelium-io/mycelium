from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, TypeVar, cast

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

if TYPE_CHECKING:
    from ..models.cfn_relation_attributes import CfnRelationAttributes


T = TypeVar("T", bound="CfnRelation")


@_attrs_define
class CfnRelation:
    """
    Attributes:
        id (str):
        node_ids (list[str]):
        relationship (str):
        attributes (CfnRelationAttributes | Unset):
    """

    id: str
    node_ids: list[str]
    relationship: str
    attributes: CfnRelationAttributes | Unset = UNSET
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        id = self.id

        node_ids = self.node_ids

        relationship = self.relationship

        attributes: dict[str, Any] | Unset = UNSET
        if not isinstance(self.attributes, Unset):
            attributes = self.attributes.to_dict()

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "id": id,
                "node_ids": node_ids,
                "relationship": relationship,
            }
        )
        if attributes is not UNSET:
            field_dict["attributes"] = attributes

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.cfn_relation_attributes import CfnRelationAttributes

        d = dict(src_dict)
        id = d.pop("id")

        node_ids = cast(list[str], d.pop("node_ids"))

        relationship = d.pop("relationship")

        _attributes = d.pop("attributes", UNSET)
        attributes: CfnRelationAttributes | Unset
        if isinstance(_attributes, Unset):
            attributes = UNSET
        else:
            attributes = CfnRelationAttributes.from_dict(_attributes)

        cfn_relation = cls(
            id=id,
            node_ids=node_ids,
            relationship=relationship,
            attributes=attributes,
        )

        cfn_relation.additional_properties = d
        return cfn_relation

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
