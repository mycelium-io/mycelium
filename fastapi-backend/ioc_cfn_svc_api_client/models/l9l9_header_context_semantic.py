from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, TypeVar

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

if TYPE_CHECKING:
    from ..models.l9l9_header_context_semantic_provenance import L9L9HeaderContextSemanticProvenance


T = TypeVar("T", bound="L9L9HeaderContextSemantic")


@_attrs_define
class L9L9HeaderContextSemantic:
    """
    Attributes:
        ontology_ref (str | Unset): OntologyRef corresponds to the JSON schema field "ontology_ref".
        provenance (L9L9HeaderContextSemanticProvenance | Unset):
        schema_id (str | Unset): SchemaID corresponds to the JSON schema field "schema_id".
    """

    ontology_ref: str | Unset = UNSET
    provenance: L9L9HeaderContextSemanticProvenance | Unset = UNSET
    schema_id: str | Unset = UNSET
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        ontology_ref = self.ontology_ref

        provenance: dict[str, Any] | Unset = UNSET
        if not isinstance(self.provenance, Unset):
            provenance = self.provenance.to_dict()

        schema_id = self.schema_id

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update({})
        if ontology_ref is not UNSET:
            field_dict["ontology_ref"] = ontology_ref
        if provenance is not UNSET:
            field_dict["provenance"] = provenance
        if schema_id is not UNSET:
            field_dict["schema_id"] = schema_id

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.l9l9_header_context_semantic_provenance import (
            L9L9HeaderContextSemanticProvenance,
        )

        d = dict(src_dict)
        ontology_ref = d.pop("ontology_ref", UNSET)

        _provenance = d.pop("provenance", UNSET)
        provenance: L9L9HeaderContextSemanticProvenance | Unset
        if isinstance(_provenance, Unset):
            provenance = UNSET
        else:
            provenance = L9L9HeaderContextSemanticProvenance.from_dict(_provenance)

        schema_id = d.pop("schema_id", UNSET)

        l9l9_header_context_semantic = cls(
            ontology_ref=ontology_ref,
            provenance=provenance,
            schema_id=schema_id,
        )

        l9l9_header_context_semantic.additional_properties = d
        return l9l9_header_context_semantic

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
