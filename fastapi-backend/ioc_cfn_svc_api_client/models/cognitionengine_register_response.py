from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

T = TypeVar("T", bound="CognitionengineRegisterResponse")


@_attrs_define
class CognitionengineRegisterResponse:
    """
    Attributes:
        ce_id (str | Unset):
        cfn_id (str | Unset):
        created (bool | Unset):
        enabled (bool | Unset):
        kind (str | Unset):
        mas_auto_associate (bool | Unset):
        name (str | Unset):
        status (str | Unset):
        subkind (str | Unset):
        version (str | Unset):
    """

    ce_id: str | Unset = UNSET
    cfn_id: str | Unset = UNSET
    created: bool | Unset = UNSET
    enabled: bool | Unset = UNSET
    kind: str | Unset = UNSET
    mas_auto_associate: bool | Unset = UNSET
    name: str | Unset = UNSET
    status: str | Unset = UNSET
    subkind: str | Unset = UNSET
    version: str | Unset = UNSET
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        ce_id = self.ce_id

        cfn_id = self.cfn_id

        created = self.created

        enabled = self.enabled

        kind = self.kind

        mas_auto_associate = self.mas_auto_associate

        name = self.name

        status = self.status

        subkind = self.subkind

        version = self.version

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update({})
        if ce_id is not UNSET:
            field_dict["ce_id"] = ce_id
        if cfn_id is not UNSET:
            field_dict["cfn_id"] = cfn_id
        if created is not UNSET:
            field_dict["created"] = created
        if enabled is not UNSET:
            field_dict["enabled"] = enabled
        if kind is not UNSET:
            field_dict["kind"] = kind
        if mas_auto_associate is not UNSET:
            field_dict["mas_auto_associate"] = mas_auto_associate
        if name is not UNSET:
            field_dict["name"] = name
        if status is not UNSET:
            field_dict["status"] = status
        if subkind is not UNSET:
            field_dict["subkind"] = subkind
        if version is not UNSET:
            field_dict["version"] = version

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        ce_id = d.pop("ce_id", UNSET)

        cfn_id = d.pop("cfn_id", UNSET)

        created = d.pop("created", UNSET)

        enabled = d.pop("enabled", UNSET)

        kind = d.pop("kind", UNSET)

        mas_auto_associate = d.pop("mas_auto_associate", UNSET)

        name = d.pop("name", UNSET)

        status = d.pop("status", UNSET)

        subkind = d.pop("subkind", UNSET)

        version = d.pop("version", UNSET)

        cognitionengine_register_response = cls(
            ce_id=ce_id,
            cfn_id=cfn_id,
            created=created,
            enabled=enabled,
            kind=kind,
            mas_auto_associate=mas_auto_associate,
            name=name,
            status=status,
            subkind=subkind,
            version=version,
        )

        cognitionengine_register_response.additional_properties = d
        return cognitionengine_register_response

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
