from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, TypeVar

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

if TYPE_CHECKING:
    from ..models.sharedmemory_header import SharedmemoryHeader
    from ..models.sharedmemory_vector_similarity_search_result import (
        SharedmemoryVectorSimilaritySearchResult,
    )


T = TypeVar("T", bound="SharedmemoryVectorSimilaritySearchResponse")


@_attrs_define
class SharedmemoryVectorSimilaritySearchResponse:
    """
    Attributes:
        header (SharedmemoryHeader | Unset):
        request_id (str | Unset):
        results (list[SharedmemoryVectorSimilaritySearchResult] | Unset):
    """

    header: SharedmemoryHeader | Unset = UNSET
    request_id: str | Unset = UNSET
    results: list[SharedmemoryVectorSimilaritySearchResult] | Unset = UNSET
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        header: dict[str, Any] | Unset = UNSET
        if not isinstance(self.header, Unset):
            header = self.header.to_dict()

        request_id = self.request_id

        results: list[dict[str, Any]] | Unset = UNSET
        if not isinstance(self.results, Unset):
            results = []
            for results_item_data in self.results:
                results_item = results_item_data.to_dict()
                results.append(results_item)

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update({})
        if header is not UNSET:
            field_dict["header"] = header
        if request_id is not UNSET:
            field_dict["request_id"] = request_id
        if results is not UNSET:
            field_dict["results"] = results

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.sharedmemory_header import SharedmemoryHeader
        from ..models.sharedmemory_vector_similarity_search_result import (
            SharedmemoryVectorSimilaritySearchResult,
        )

        d = dict(src_dict)
        _header = d.pop("header", UNSET)
        header: SharedmemoryHeader | Unset
        if isinstance(_header, Unset):
            header = UNSET
        else:
            header = SharedmemoryHeader.from_dict(_header)

        request_id = d.pop("request_id", UNSET)

        _results = d.pop("results", UNSET)
        results: list[SharedmemoryVectorSimilaritySearchResult] | Unset = UNSET
        if _results is not UNSET:
            results = []
            for results_item_data in _results:
                results_item = SharedmemoryVectorSimilaritySearchResult.from_dict(results_item_data)

                results.append(results_item)

        sharedmemory_vector_similarity_search_response = cls(
            header=header,
            request_id=request_id,
            results=results,
        )

        sharedmemory_vector_similarity_search_response.additional_properties = d
        return sharedmemory_vector_similarity_search_response

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
