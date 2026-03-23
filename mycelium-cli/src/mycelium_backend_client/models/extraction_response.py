from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, TypeVar

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

if TYPE_CHECKING:
    from ..models.cfn_concept import CfnConcept
    from ..models.cfn_header import CfnHeader
    from ..models.cfn_relation import CfnRelation
    from ..models.extraction_meta import ExtractionMeta


T = TypeVar("T", bound="ExtractionResponse")


@_attrs_define
class ExtractionResponse:
    """
    Attributes:
        header (CfnHeader):
        response_id (str):
        concepts (list[CfnConcept] | Unset):
        relations (list[CfnRelation] | Unset):
        descriptor (str | Unset):  Default: 'openclaw'.
        metadata (ExtractionMeta | Unset):
    """

    header: CfnHeader
    response_id: str
    concepts: list[CfnConcept] | Unset = UNSET
    relations: list[CfnRelation] | Unset = UNSET
    descriptor: str | Unset = "openclaw"
    metadata: ExtractionMeta | Unset = UNSET
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        header = self.header.to_dict()

        response_id = self.response_id

        concepts: list[dict[str, Any]] | Unset = UNSET
        if not isinstance(self.concepts, Unset):
            concepts = []
            for concepts_item_data in self.concepts:
                concepts_item = concepts_item_data.to_dict()
                concepts.append(concepts_item)

        relations: list[dict[str, Any]] | Unset = UNSET
        if not isinstance(self.relations, Unset):
            relations = []
            for relations_item_data in self.relations:
                relations_item = relations_item_data.to_dict()
                relations.append(relations_item)

        descriptor = self.descriptor

        metadata: dict[str, Any] | Unset = UNSET
        if not isinstance(self.metadata, Unset):
            metadata = self.metadata.to_dict()

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "header": header,
                "response_id": response_id,
            }
        )
        if concepts is not UNSET:
            field_dict["concepts"] = concepts
        if relations is not UNSET:
            field_dict["relations"] = relations
        if descriptor is not UNSET:
            field_dict["descriptor"] = descriptor
        if metadata is not UNSET:
            field_dict["metadata"] = metadata

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.cfn_concept import CfnConcept
        from ..models.cfn_header import CfnHeader
        from ..models.cfn_relation import CfnRelation
        from ..models.extraction_meta import ExtractionMeta

        d = dict(src_dict)
        header = CfnHeader.from_dict(d.pop("header"))

        response_id = d.pop("response_id")

        _concepts = d.pop("concepts", UNSET)
        concepts: list[CfnConcept] | Unset = UNSET
        if _concepts is not UNSET:
            concepts = []
            for concepts_item_data in _concepts:
                concepts_item = CfnConcept.from_dict(concepts_item_data)

                concepts.append(concepts_item)

        _relations = d.pop("relations", UNSET)
        relations: list[CfnRelation] | Unset = UNSET
        if _relations is not UNSET:
            relations = []
            for relations_item_data in _relations:
                relations_item = CfnRelation.from_dict(relations_item_data)

                relations.append(relations_item)

        descriptor = d.pop("descriptor", UNSET)

        _metadata = d.pop("metadata", UNSET)
        metadata: ExtractionMeta | Unset
        if isinstance(_metadata, Unset):
            metadata = UNSET
        else:
            metadata = ExtractionMeta.from_dict(_metadata)

        extraction_response = cls(
            header=header,
            response_id=response_id,
            concepts=concepts,
            relations=relations,
            descriptor=descriptor,
            metadata=metadata,
        )

        extraction_response.additional_properties = d
        return extraction_response

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
