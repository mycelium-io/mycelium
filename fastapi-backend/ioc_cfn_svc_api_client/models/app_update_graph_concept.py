from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, TypeVar

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

if TYPE_CHECKING:
    from ..models.app_update_graph_concept_attributes import AppUpdateGraphConceptAttributes
    from ..models.iocmemoryprovider_internal_attributes import IocmemoryproviderInternalAttributes


T = TypeVar("T", bound="AppUpdateGraphConcept")


@_attrs_define
class AppUpdateGraphConcept:
    """
    Attributes:
        attributes (AppUpdateGraphConceptAttributes | Unset):
        description (str | Unset):
        id (str | Unset):
        internal_attributes (list[IocmemoryproviderInternalAttributes] | Unset):
        name (str | Unset):
    """

    attributes: AppUpdateGraphConceptAttributes | Unset = UNSET
    description: str | Unset = UNSET
    id: str | Unset = UNSET
    internal_attributes: list[IocmemoryproviderInternalAttributes] | Unset = UNSET
    name: str | Unset = UNSET
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        attributes: dict[str, Any] | Unset = UNSET
        if not isinstance(self.attributes, Unset):
            attributes = self.attributes.to_dict()

        description = self.description

        id = self.id

        internal_attributes: list[dict[str, Any]] | Unset = UNSET
        if not isinstance(self.internal_attributes, Unset):
            internal_attributes = []
            for internal_attributes_item_data in self.internal_attributes:
                internal_attributes_item = internal_attributes_item_data.to_dict()
                internal_attributes.append(internal_attributes_item)

        name = self.name

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update({})
        if attributes is not UNSET:
            field_dict["attributes"] = attributes
        if description is not UNSET:
            field_dict["description"] = description
        if id is not UNSET:
            field_dict["id"] = id
        if internal_attributes is not UNSET:
            field_dict["internal_attributes"] = internal_attributes
        if name is not UNSET:
            field_dict["name"] = name

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.app_update_graph_concept_attributes import AppUpdateGraphConceptAttributes
        from ..models.iocmemoryprovider_internal_attributes import (
            IocmemoryproviderInternalAttributes,
        )

        d = dict(src_dict)
        _attributes = d.pop("attributes", UNSET)
        attributes: AppUpdateGraphConceptAttributes | Unset
        if isinstance(_attributes, Unset):
            attributes = UNSET
        else:
            attributes = AppUpdateGraphConceptAttributes.from_dict(_attributes)

        description = d.pop("description", UNSET)

        id = d.pop("id", UNSET)

        _internal_attributes = d.pop("internal_attributes", UNSET)
        internal_attributes: list[IocmemoryproviderInternalAttributes] | Unset = UNSET
        if _internal_attributes is not UNSET:
            internal_attributes = []
            for internal_attributes_item_data in _internal_attributes:
                internal_attributes_item = IocmemoryproviderInternalAttributes.from_dict(
                    internal_attributes_item_data
                )

                internal_attributes.append(internal_attributes_item)

        name = d.pop("name", UNSET)

        app_update_graph_concept = cls(
            attributes=attributes,
            description=description,
            id=id,
            internal_attributes=internal_attributes,
            name=name,
        )

        app_update_graph_concept.additional_properties = d
        return app_update_graph_concept

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
