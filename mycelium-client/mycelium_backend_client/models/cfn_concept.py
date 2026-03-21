from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, TypeVar

from attrs import define as _attrs_define
from attrs import field as _attrs_field

if TYPE_CHECKING:
    from ..models.concept_attributes import ConceptAttributes


T = TypeVar("T", bound="CfnConcept")


@_attrs_define
class CfnConcept:
    """
    Attributes:
        id (str):
        name (str):
        description (str):
        type_ (str):
        attributes (ConceptAttributes):
    """

    id: str
    name: str
    description: str
    type_: str
    attributes: ConceptAttributes
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        id = self.id

        name = self.name

        description = self.description

        type_ = self.type_

        attributes = self.attributes.to_dict()

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "id": id,
                "name": name,
                "description": description,
                "type": type_,
                "attributes": attributes,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.concept_attributes import ConceptAttributes

        d = dict(src_dict)
        id = d.pop("id")

        name = d.pop("name")

        description = d.pop("description")

        type_ = d.pop("type")

        attributes = ConceptAttributes.from_dict(d.pop("attributes"))

        cfn_concept = cls(
            id=id,
            name=name,
            description=description,
            type_=type_,
            attributes=attributes,
        )

        cfn_concept.additional_properties = d
        return cfn_concept

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
