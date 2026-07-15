from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, TypeVar

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

if TYPE_CHECKING:
    from ..models.sharedmemory_path import SharedmemoryPath


T = TypeVar("T", bound="SharedmemoryGraphPathsResponse")


@_attrs_define
class SharedmemoryGraphPathsResponse:
    """
    Attributes:
        paths (list[SharedmemoryPath] | Unset):
        status (str | Unset):
    """

    paths: list[SharedmemoryPath] | Unset = UNSET
    status: str | Unset = UNSET
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        paths: list[dict[str, Any]] | Unset = UNSET
        if not isinstance(self.paths, Unset):
            paths = []
            for paths_item_data in self.paths:
                paths_item = paths_item_data.to_dict()
                paths.append(paths_item)

        status = self.status

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update({})
        if paths is not UNSET:
            field_dict["paths"] = paths
        if status is not UNSET:
            field_dict["status"] = status

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.sharedmemory_path import SharedmemoryPath

        d = dict(src_dict)
        _paths = d.pop("paths", UNSET)
        paths: list[SharedmemoryPath] | Unset = UNSET
        if _paths is not UNSET:
            paths = []
            for paths_item_data in _paths:
                paths_item = SharedmemoryPath.from_dict(paths_item_data)

                paths.append(paths_item)

        status = d.pop("status", UNSET)

        sharedmemory_graph_paths_response = cls(
            paths=paths,
            status=status,
        )

        sharedmemory_graph_paths_response.additional_properties = d
        return sharedmemory_graph_paths_response

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
