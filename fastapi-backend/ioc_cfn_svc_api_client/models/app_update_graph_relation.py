from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, TypeVar, cast

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

if TYPE_CHECKING:
    from ..models.app_update_graph_relation_attributes import AppUpdateGraphRelationAttributes
    from ..models.iocmemoryprovider_internal_attributes import IocmemoryproviderInternalAttributes


T = TypeVar("T", bound="AppUpdateGraphRelation")


@_attrs_define
class AppUpdateGraphRelation:
    """
    Attributes:
        attributes (AppUpdateGraphRelationAttributes | Unset):
        id (str | Unset):
        internal_attributes (list[IocmemoryproviderInternalAttributes] | Unset):
        node_ids (list[str] | Unset):
        relationship (str | Unset):
    """

    attributes: AppUpdateGraphRelationAttributes | Unset = UNSET
    id: str | Unset = UNSET
    internal_attributes: list[IocmemoryproviderInternalAttributes] | Unset = UNSET
    node_ids: list[str] | Unset = UNSET
    relationship: str | Unset = UNSET
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        attributes: dict[str, Any] | Unset = UNSET
        if not isinstance(self.attributes, Unset):
            attributes = self.attributes.to_dict()

        id = self.id

        internal_attributes: list[dict[str, Any]] | Unset = UNSET
        if not isinstance(self.internal_attributes, Unset):
            internal_attributes = []
            for internal_attributes_item_data in self.internal_attributes:
                internal_attributes_item = internal_attributes_item_data.to_dict()
                internal_attributes.append(internal_attributes_item)

        node_ids: list[str] | Unset = UNSET
        if not isinstance(self.node_ids, Unset):
            node_ids = self.node_ids

        relationship = self.relationship

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update({})
        if attributes is not UNSET:
            field_dict["attributes"] = attributes
        if id is not UNSET:
            field_dict["id"] = id
        if internal_attributes is not UNSET:
            field_dict["internal_attributes"] = internal_attributes
        if node_ids is not UNSET:
            field_dict["node_ids"] = node_ids
        if relationship is not UNSET:
            field_dict["relationship"] = relationship

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.app_update_graph_relation_attributes import AppUpdateGraphRelationAttributes
        from ..models.iocmemoryprovider_internal_attributes import (
            IocmemoryproviderInternalAttributes,
        )

        d = dict(src_dict)
        _attributes = d.pop("attributes", UNSET)
        attributes: AppUpdateGraphRelationAttributes | Unset
        if isinstance(_attributes, Unset):
            attributes = UNSET
        else:
            attributes = AppUpdateGraphRelationAttributes.from_dict(_attributes)

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

        node_ids = cast(list[str], d.pop("node_ids", UNSET))

        relationship = d.pop("relationship", UNSET)

        app_update_graph_relation = cls(
            attributes=attributes,
            id=id,
            internal_attributes=internal_attributes,
            node_ids=node_ids,
            relationship=relationship,
        )

        app_update_graph_relation.additional_properties = d
        return app_update_graph_relation

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
