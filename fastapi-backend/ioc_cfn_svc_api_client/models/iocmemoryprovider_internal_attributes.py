from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, TypeVar

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

if TYPE_CHECKING:
    from ..models.iocmemoryprovider_internal_attributes_attributes import (
        IocmemoryproviderInternalAttributesAttributes,
    )


T = TypeVar("T", bound="IocmemoryproviderInternalAttributes")


@_attrs_define
class IocmemoryproviderInternalAttributes:
    """
    Attributes:
        attributes (IocmemoryproviderInternalAttributesAttributes | Unset):
        owner (str | Unset):
    """

    attributes: IocmemoryproviderInternalAttributesAttributes | Unset = UNSET
    owner: str | Unset = UNSET
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        attributes: dict[str, Any] | Unset = UNSET
        if not isinstance(self.attributes, Unset):
            attributes = self.attributes.to_dict()

        owner = self.owner

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update({})
        if attributes is not UNSET:
            field_dict["attributes"] = attributes
        if owner is not UNSET:
            field_dict["owner"] = owner

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.iocmemoryprovider_internal_attributes_attributes import (
            IocmemoryproviderInternalAttributesAttributes,
        )

        d = dict(src_dict)
        _attributes = d.pop("attributes", UNSET)
        attributes: IocmemoryproviderInternalAttributesAttributes | Unset
        if isinstance(_attributes, Unset):
            attributes = UNSET
        else:
            attributes = IocmemoryproviderInternalAttributesAttributes.from_dict(_attributes)

        owner = d.pop("owner", UNSET)

        iocmemoryprovider_internal_attributes = cls(
            attributes=attributes,
            owner=owner,
        )

        iocmemoryprovider_internal_attributes.additional_properties = d
        return iocmemoryprovider_internal_attributes

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
