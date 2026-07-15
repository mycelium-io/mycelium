from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, cast

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

T = TypeVar("T", bound="SharedmemoryGraphPathsRequest")


@_attrs_define
class SharedmemoryGraphPathsRequest:
    """
    Attributes:
        limit (int | Unset):
        max_depth (int | Unset):
        relations (list[str] | Unset):
        source_id (str | Unset):
        target_id (str | Unset):
    """

    limit: int | Unset = UNSET
    max_depth: int | Unset = UNSET
    relations: list[str] | Unset = UNSET
    source_id: str | Unset = UNSET
    target_id: str | Unset = UNSET
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        limit = self.limit

        max_depth = self.max_depth

        relations: list[str] | Unset = UNSET
        if not isinstance(self.relations, Unset):
            relations = self.relations

        source_id = self.source_id

        target_id = self.target_id

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update({})
        if limit is not UNSET:
            field_dict["limit"] = limit
        if max_depth is not UNSET:
            field_dict["max_depth"] = max_depth
        if relations is not UNSET:
            field_dict["relations"] = relations
        if source_id is not UNSET:
            field_dict["source_id"] = source_id
        if target_id is not UNSET:
            field_dict["target_id"] = target_id

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        limit = d.pop("limit", UNSET)

        max_depth = d.pop("max_depth", UNSET)

        relations = cast(list[str], d.pop("relations", UNSET))

        source_id = d.pop("source_id", UNSET)

        target_id = d.pop("target_id", UNSET)

        sharedmemory_graph_paths_request = cls(
            limit=limit,
            max_depth=max_depth,
            relations=relations,
            source_id=source_id,
            target_id=target_id,
        )

        sharedmemory_graph_paths_request.additional_properties = d
        return sharedmemory_graph_paths_request

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
