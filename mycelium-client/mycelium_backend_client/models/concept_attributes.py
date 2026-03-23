from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, cast

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

T = TypeVar("T", bound="ConceptAttributes")


@_attrs_define
class ConceptAttributes:
    """
    Attributes:
        concept_type (str):
        embedding (list[list[float]] | None | Unset):
    """

    concept_type: str
    embedding: list[list[float]] | None | Unset = UNSET
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        concept_type = self.concept_type

        embedding: list[list[float]] | None | Unset
        if isinstance(self.embedding, Unset):
            embedding = UNSET
        elif isinstance(self.embedding, list):
            embedding = []
            for embedding_type_0_item_data in self.embedding:
                embedding_type_0_item = embedding_type_0_item_data

                embedding.append(embedding_type_0_item)

        else:
            embedding = self.embedding

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "concept_type": concept_type,
            }
        )
        if embedding is not UNSET:
            field_dict["embedding"] = embedding

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        concept_type = d.pop("concept_type")

        def _parse_embedding(data: object) -> list[list[float]] | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            try:
                if not isinstance(data, list):
                    raise TypeError()
                embedding_type_0 = []
                _embedding_type_0 = data
                for embedding_type_0_item_data in _embedding_type_0:
                    embedding_type_0_item = cast(list[float], embedding_type_0_item_data)

                    embedding_type_0.append(embedding_type_0_item)

                return embedding_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(list[list[float]] | None | Unset, data)

        embedding = _parse_embedding(d.pop("embedding", UNSET))

        concept_attributes = cls(
            concept_type=concept_type,
            embedding=embedding,
        )

        concept_attributes.additional_properties = d
        return concept_attributes

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
