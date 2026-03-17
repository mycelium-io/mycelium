from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, TypeVar

from attrs import define as _attrs_define
from attrs import field as _attrs_field

if TYPE_CHECKING:
    from ..models.memory_read import MemoryRead


T = TypeVar("T", bound="MemorySearchResult")


@_attrs_define
class MemorySearchResult:
    """
    Attributes:
        memory (MemoryRead):
        similarity (float):
    """

    memory: MemoryRead
    similarity: float
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        memory = self.memory.to_dict()

        similarity = self.similarity

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "memory": memory,
                "similarity": similarity,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.memory_read import MemoryRead

        d = dict(src_dict)
        memory = MemoryRead.from_dict(d.pop("memory"))

        similarity = d.pop("similarity")

        memory_search_result = cls(
            memory=memory,
            similarity=similarity,
        )

        memory_search_result.additional_properties = d
        return memory_search_result

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
