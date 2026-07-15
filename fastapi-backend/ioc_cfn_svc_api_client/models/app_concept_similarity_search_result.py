from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, cast

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

T = TypeVar("T", bound="AppConceptSimilaritySearchResult")


@_attrs_define
class AppConceptSimilaritySearchResult:
    """
    Attributes:
        concept_id (str | Unset):
        concept_name (str | Unset):
        embedding_vector (list[float] | Unset):
        score (float | Unset):
    """

    concept_id: str | Unset = UNSET
    concept_name: str | Unset = UNSET
    embedding_vector: list[float] | Unset = UNSET
    score: float | Unset = UNSET
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        concept_id = self.concept_id

        concept_name = self.concept_name

        embedding_vector: list[float] | Unset = UNSET
        if not isinstance(self.embedding_vector, Unset):
            embedding_vector = self.embedding_vector

        score = self.score

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update({})
        if concept_id is not UNSET:
            field_dict["concept_id"] = concept_id
        if concept_name is not UNSET:
            field_dict["concept_name"] = concept_name
        if embedding_vector is not UNSET:
            field_dict["embedding_vector"] = embedding_vector
        if score is not UNSET:
            field_dict["score"] = score

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        concept_id = d.pop("concept_id", UNSET)

        concept_name = d.pop("concept_name", UNSET)

        embedding_vector = cast(list[float], d.pop("embedding_vector", UNSET))

        score = d.pop("score", UNSET)

        app_concept_similarity_search_result = cls(
            concept_id=concept_id,
            concept_name=concept_name,
            embedding_vector=embedding_vector,
            score=score,
        )

        app_concept_similarity_search_result.additional_properties = d
        return app_concept_similarity_search_result

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
