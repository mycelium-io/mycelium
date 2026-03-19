from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, cast

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

T = TypeVar("T", bound="MemorySearchRequest")


@_attrs_define
class MemorySearchRequest:
    """
    Attributes:
        query (str):
        limit (int | Unset):  Default: 10.
        tags_filter (list[str] | None | Unset):
        min_similarity (float | Unset):  Default: 0.0.
    """

    query: str
    limit: int | Unset = 10
    tags_filter: list[str] | None | Unset = UNSET
    min_similarity: float | Unset = 0.0
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        query = self.query

        limit = self.limit

        tags_filter: list[str] | None | Unset
        if isinstance(self.tags_filter, Unset):
            tags_filter = UNSET
        elif isinstance(self.tags_filter, list):
            tags_filter = self.tags_filter

        else:
            tags_filter = self.tags_filter

        min_similarity = self.min_similarity

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "query": query,
            }
        )
        if limit is not UNSET:
            field_dict["limit"] = limit
        if tags_filter is not UNSET:
            field_dict["tags_filter"] = tags_filter
        if min_similarity is not UNSET:
            field_dict["min_similarity"] = min_similarity

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        query = d.pop("query")

        limit = d.pop("limit", UNSET)

        def _parse_tags_filter(data: object) -> list[str] | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            try:
                if not isinstance(data, list):
                    raise TypeError()
                tags_filter_type_0 = cast(list[str], data)

                return tags_filter_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(list[str] | None | Unset, data)

        tags_filter = _parse_tags_filter(d.pop("tags_filter", UNSET))

        min_similarity = d.pop("min_similarity", UNSET)

        memory_search_request = cls(
            query=query,
            limit=limit,
            tags_filter=tags_filter,
            min_similarity=min_similarity,
        )

        memory_search_request.additional_properties = d
        return memory_search_request

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
