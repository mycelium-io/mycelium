from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, cast

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

T = TypeVar("T", bound="GraphPathsRequest")


@_attrs_define
class GraphPathsRequest:
    """
    Attributes:
        source_id (str):
        target_id (str):
        limit (int | None | Unset):
        mas_id (None | str | Unset):
        max_depth (int | None | Unset):
        relations (list[str] | None | Unset):
        workspace_id (None | str | Unset):
    """

    source_id: str
    target_id: str
    limit: int | None | Unset = UNSET
    mas_id: None | str | Unset = UNSET
    max_depth: int | None | Unset = UNSET
    relations: list[str] | None | Unset = UNSET
    workspace_id: None | str | Unset = UNSET
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        source_id = self.source_id

        target_id = self.target_id

        limit: int | None | Unset
        if isinstance(self.limit, Unset):
            limit = UNSET
        else:
            limit = self.limit

        mas_id: None | str | Unset
        if isinstance(self.mas_id, Unset):
            mas_id = UNSET
        else:
            mas_id = self.mas_id

        max_depth: int | None | Unset
        if isinstance(self.max_depth, Unset):
            max_depth = UNSET
        else:
            max_depth = self.max_depth

        relations: list[str] | None | Unset
        if isinstance(self.relations, Unset):
            relations = UNSET
        elif isinstance(self.relations, list):
            relations = self.relations

        else:
            relations = self.relations

        workspace_id: None | str | Unset
        if isinstance(self.workspace_id, Unset):
            workspace_id = UNSET
        else:
            workspace_id = self.workspace_id

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "source_id": source_id,
                "target_id": target_id,
            }
        )
        if limit is not UNSET:
            field_dict["limit"] = limit
        if mas_id is not UNSET:
            field_dict["mas_id"] = mas_id
        if max_depth is not UNSET:
            field_dict["max_depth"] = max_depth
        if relations is not UNSET:
            field_dict["relations"] = relations
        if workspace_id is not UNSET:
            field_dict["workspace_id"] = workspace_id

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        source_id = d.pop("source_id")

        target_id = d.pop("target_id")

        def _parse_limit(data: object) -> int | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(int | None | Unset, data)

        limit = _parse_limit(d.pop("limit", UNSET))

        def _parse_mas_id(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        mas_id = _parse_mas_id(d.pop("mas_id", UNSET))

        def _parse_max_depth(data: object) -> int | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(int | None | Unset, data)

        max_depth = _parse_max_depth(d.pop("max_depth", UNSET))

        def _parse_relations(data: object) -> list[str] | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            try:
                if not isinstance(data, list):
                    raise TypeError()
                relations_type_0 = cast(list[str], data)

                return relations_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(list[str] | None | Unset, data)

        relations = _parse_relations(d.pop("relations", UNSET))

        def _parse_workspace_id(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        workspace_id = _parse_workspace_id(d.pop("workspace_id", UNSET))

        graph_paths_request = cls(
            source_id=source_id,
            target_id=target_id,
            limit=limit,
            mas_id=mas_id,
            max_depth=max_depth,
            relations=relations,
            workspace_id=workspace_id,
        )

        graph_paths_request.additional_properties = d
        return graph_paths_request

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
