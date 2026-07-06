from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, TypeVar

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

if TYPE_CHECKING:
    from ..models.app_concept_similarity_search_response_header import (
        AppConceptSimilaritySearchResponseHeader,
    )
    from ..models.app_concept_similarity_search_result import AppConceptSimilaritySearchResult


T = TypeVar("T", bound="AppConceptSimilaritySearchResponse")


@_attrs_define
class AppConceptSimilaritySearchResponse:
    """
    Attributes:
        error (str | Unset):
        header (AppConceptSimilaritySearchResponseHeader | Unset):
        response_id (str | Unset):
        results (list[AppConceptSimilaritySearchResult] | Unset):
        status (str | Unset):
    """

    error: str | Unset = UNSET
    header: AppConceptSimilaritySearchResponseHeader | Unset = UNSET
    response_id: str | Unset = UNSET
    results: list[AppConceptSimilaritySearchResult] | Unset = UNSET
    status: str | Unset = UNSET
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        error = self.error

        header: dict[str, Any] | Unset = UNSET
        if not isinstance(self.header, Unset):
            header = self.header.to_dict()

        response_id = self.response_id

        results: list[dict[str, Any]] | Unset = UNSET
        if not isinstance(self.results, Unset):
            results = []
            for results_item_data in self.results:
                results_item = results_item_data.to_dict()
                results.append(results_item)

        status = self.status

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update({})
        if error is not UNSET:
            field_dict["error"] = error
        if header is not UNSET:
            field_dict["header"] = header
        if response_id is not UNSET:
            field_dict["response_id"] = response_id
        if results is not UNSET:
            field_dict["results"] = results
        if status is not UNSET:
            field_dict["status"] = status

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.app_concept_similarity_search_response_header import (
            AppConceptSimilaritySearchResponseHeader,
        )
        from ..models.app_concept_similarity_search_result import AppConceptSimilaritySearchResult

        d = dict(src_dict)
        error = d.pop("error", UNSET)

        _header = d.pop("header", UNSET)
        header: AppConceptSimilaritySearchResponseHeader | Unset
        if isinstance(_header, Unset):
            header = UNSET
        else:
            header = AppConceptSimilaritySearchResponseHeader.from_dict(_header)

        response_id = d.pop("response_id", UNSET)

        _results = d.pop("results", UNSET)
        results: list[AppConceptSimilaritySearchResult] | Unset = UNSET
        if _results is not UNSET:
            results = []
            for results_item_data in _results:
                results_item = AppConceptSimilaritySearchResult.from_dict(results_item_data)

                results.append(results_item)

        status = d.pop("status", UNSET)

        app_concept_similarity_search_response = cls(
            error=error,
            header=header,
            response_id=response_id,
            results=results,
            status=status,
        )

        app_concept_similarity_search_response.additional_properties = d
        return app_concept_similarity_search_response

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
