from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

T = TypeVar("T", bound="SemanticalignmentSharedMemoryResult")


@_attrs_define
class SemanticalignmentSharedMemoryResult:
    """
    Attributes:
        error (str | Unset): Error contains a human-readable reason when Persisted is false.
        persisted (bool | Unset): Persisted is true when the agreement was successfully written to shared memory.
    """

    error: str | Unset = UNSET
    persisted: bool | Unset = UNSET
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        error = self.error

        persisted = self.persisted

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update({})
        if error is not UNSET:
            field_dict["error"] = error
        if persisted is not UNSET:
            field_dict["persisted"] = persisted

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        error = d.pop("error", UNSET)

        persisted = d.pop("persisted", UNSET)

        semanticalignment_shared_memory_result = cls(
            error=error,
            persisted=persisted,
        )

        semanticalignment_shared_memory_result.additional_properties = d
        return semanticalignment_shared_memory_result

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
