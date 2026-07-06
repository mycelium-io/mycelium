from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, TypeVar, cast

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

if TYPE_CHECKING:
    from ..models.sharedmemory_path_edge import SharedmemoryPathEdge


T = TypeVar("T", bound="SharedmemoryPath")


@_attrs_define
class SharedmemoryPath:
    """
    Attributes:
        edges (list[SharedmemoryPathEdge] | Unset):
        node_ids (list[str] | Unset):
        path_length (int | Unset):
        symbolic (str | Unset):
    """

    edges: list[SharedmemoryPathEdge] | Unset = UNSET
    node_ids: list[str] | Unset = UNSET
    path_length: int | Unset = UNSET
    symbolic: str | Unset = UNSET
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        edges: list[dict[str, Any]] | Unset = UNSET
        if not isinstance(self.edges, Unset):
            edges = []
            for edges_item_data in self.edges:
                edges_item = edges_item_data.to_dict()
                edges.append(edges_item)

        node_ids: list[str] | Unset = UNSET
        if not isinstance(self.node_ids, Unset):
            node_ids = self.node_ids

        path_length = self.path_length

        symbolic = self.symbolic

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update({})
        if edges is not UNSET:
            field_dict["edges"] = edges
        if node_ids is not UNSET:
            field_dict["node_ids"] = node_ids
        if path_length is not UNSET:
            field_dict["path_length"] = path_length
        if symbolic is not UNSET:
            field_dict["symbolic"] = symbolic

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.sharedmemory_path_edge import SharedmemoryPathEdge

        d = dict(src_dict)
        _edges = d.pop("edges", UNSET)
        edges: list[SharedmemoryPathEdge] | Unset = UNSET
        if _edges is not UNSET:
            edges = []
            for edges_item_data in _edges:
                edges_item = SharedmemoryPathEdge.from_dict(edges_item_data)

                edges.append(edges_item)

        node_ids = cast(list[str], d.pop("node_ids", UNSET))

        path_length = d.pop("path_length", UNSET)

        symbolic = d.pop("symbolic", UNSET)

        sharedmemory_path = cls(
            edges=edges,
            node_ids=node_ids,
            path_length=path_length,
            symbolic=symbolic,
        )

        sharedmemory_path.additional_properties = d
        return sharedmemory_path

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
