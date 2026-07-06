from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, cast

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

T = TypeVar("T", bound="SharedmemoryVectorSimilaritySearchResult")


@_attrs_define
class SharedmemoryVectorSimilaritySearchResult:
    """
    Attributes:
        chunk_index (int | Unset):
        doc_index (int | Unset):
        domain (str | Unset):
        embedded_text (str | Unset):
        embedding_vector (list[float] | Unset):
        score (float | Unset):
        timestamp (str | Unset):
    """

    chunk_index: int | Unset = UNSET
    doc_index: int | Unset = UNSET
    domain: str | Unset = UNSET
    embedded_text: str | Unset = UNSET
    embedding_vector: list[float] | Unset = UNSET
    score: float | Unset = UNSET
    timestamp: str | Unset = UNSET
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        chunk_index = self.chunk_index

        doc_index = self.doc_index

        domain = self.domain

        embedded_text = self.embedded_text

        embedding_vector: list[float] | Unset = UNSET
        if not isinstance(self.embedding_vector, Unset):
            embedding_vector = self.embedding_vector

        score = self.score

        timestamp = self.timestamp

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update({})
        if chunk_index is not UNSET:
            field_dict["chunk_index"] = chunk_index
        if doc_index is not UNSET:
            field_dict["doc_index"] = doc_index
        if domain is not UNSET:
            field_dict["domain"] = domain
        if embedded_text is not UNSET:
            field_dict["embedded_text"] = embedded_text
        if embedding_vector is not UNSET:
            field_dict["embedding_vector"] = embedding_vector
        if score is not UNSET:
            field_dict["score"] = score
        if timestamp is not UNSET:
            field_dict["timestamp"] = timestamp

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        chunk_index = d.pop("chunk_index", UNSET)

        doc_index = d.pop("doc_index", UNSET)

        domain = d.pop("domain", UNSET)

        embedded_text = d.pop("embedded_text", UNSET)

        embedding_vector = cast(list[float], d.pop("embedding_vector", UNSET))

        score = d.pop("score", UNSET)

        timestamp = d.pop("timestamp", UNSET)

        sharedmemory_vector_similarity_search_result = cls(
            chunk_index=chunk_index,
            doc_index=doc_index,
            domain=domain,
            embedded_text=embedded_text,
            embedding_vector=embedding_vector,
            score=score,
            timestamp=timestamp,
        )

        sharedmemory_vector_similarity_search_result.additional_properties = d
        return sharedmemory_vector_similarity_search_result

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
