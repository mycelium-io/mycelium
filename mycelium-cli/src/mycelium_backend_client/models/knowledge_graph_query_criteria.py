from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, cast

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

T = TypeVar("T", bound="KnowledgeGraphQueryCriteria")


@_attrs_define
class KnowledgeGraphQueryCriteria:
    """
    Attributes:
        depth (int | None | Unset):
        use_direction (bool | None | Unset):  Default: True.
        query_type (str | Unset):  Default: 'neighbour'.
    """

    depth: int | None | Unset = UNSET
    use_direction: bool | None | Unset = True
    query_type: str | Unset = "neighbour"
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        depth: int | None | Unset
        if isinstance(self.depth, Unset):
            depth = UNSET
        else:
            depth = self.depth

        use_direction: bool | None | Unset
        if isinstance(self.use_direction, Unset):
            use_direction = UNSET
        else:
            use_direction = self.use_direction

        query_type = self.query_type

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update({})
        if depth is not UNSET:
            field_dict["depth"] = depth
        if use_direction is not UNSET:
            field_dict["use_direction"] = use_direction
        if query_type is not UNSET:
            field_dict["query_type"] = query_type

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)

        def _parse_depth(data: object) -> int | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(int | None | Unset, data)

        depth = _parse_depth(d.pop("depth", UNSET))

        def _parse_use_direction(data: object) -> bool | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(bool | None | Unset, data)

        use_direction = _parse_use_direction(d.pop("use_direction", UNSET))

        query_type = d.pop("query_type", UNSET)

        knowledge_graph_query_criteria = cls(
            depth=depth,
            use_direction=use_direction,
            query_type=query_type,
        )

        knowledge_graph_query_criteria.additional_properties = d
        return knowledge_graph_query_criteria

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
