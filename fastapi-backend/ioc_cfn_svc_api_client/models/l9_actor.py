from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

T = TypeVar("T", bound="L9Actor")


@_attrs_define
class L9Actor:
    """
    Attributes:
        attestation (Any | Unset): Attestation corresponds to the JSON schema field "attestation".
        id (str | Unset): ID corresponds to the JSON schema field "id".
        role (str | Unset): Role corresponds to the JSON schema field "role".
    """

    attestation: Any | Unset = UNSET
    id: str | Unset = UNSET
    role: str | Unset = UNSET
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        attestation = self.attestation

        id = self.id

        role = self.role

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update({})
        if attestation is not UNSET:
            field_dict["attestation"] = attestation
        if id is not UNSET:
            field_dict["id"] = id
        if role is not UNSET:
            field_dict["role"] = role

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        attestation = d.pop("attestation", UNSET)

        id = d.pop("id", UNSET)

        role = d.pop("role", UNSET)

        l9_actor = cls(
            attestation=attestation,
            id=id,
            role=role,
        )

        l9_actor.additional_properties = d
        return l9_actor

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
