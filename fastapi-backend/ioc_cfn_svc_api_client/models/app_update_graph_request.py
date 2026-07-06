from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, TypeVar

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

if TYPE_CHECKING:
    from ..models.app_update_graph_concept import AppUpdateGraphConcept
    from ..models.app_update_graph_header import AppUpdateGraphHeader
    from ..models.app_update_graph_relation import AppUpdateGraphRelation
    from ..models.app_update_graph_request_metadata import AppUpdateGraphRequestMetadata


T = TypeVar("T", bound="AppUpdateGraphRequest")


@_attrs_define
class AppUpdateGraphRequest:
    """
    Attributes:
        concepts (list[AppUpdateGraphConcept] | Unset):
        descriptor (str | Unset):
        header (AppUpdateGraphHeader | Unset):
        metadata (AppUpdateGraphRequestMetadata | Unset):
        relations (list[AppUpdateGraphRelation] | Unset):
        request_id (str | Unset):
    """

    concepts: list[AppUpdateGraphConcept] | Unset = UNSET
    descriptor: str | Unset = UNSET
    header: AppUpdateGraphHeader | Unset = UNSET
    metadata: AppUpdateGraphRequestMetadata | Unset = UNSET
    relations: list[AppUpdateGraphRelation] | Unset = UNSET
    request_id: str | Unset = UNSET
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        concepts: list[dict[str, Any]] | Unset = UNSET
        if not isinstance(self.concepts, Unset):
            concepts = []
            for concepts_item_data in self.concepts:
                concepts_item = concepts_item_data.to_dict()
                concepts.append(concepts_item)

        descriptor = self.descriptor

        header: dict[str, Any] | Unset = UNSET
        if not isinstance(self.header, Unset):
            header = self.header.to_dict()

        metadata: dict[str, Any] | Unset = UNSET
        if not isinstance(self.metadata, Unset):
            metadata = self.metadata.to_dict()

        relations: list[dict[str, Any]] | Unset = UNSET
        if not isinstance(self.relations, Unset):
            relations = []
            for relations_item_data in self.relations:
                relations_item = relations_item_data.to_dict()
                relations.append(relations_item)

        request_id = self.request_id

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update({})
        if concepts is not UNSET:
            field_dict["concepts"] = concepts
        if descriptor is not UNSET:
            field_dict["descriptor"] = descriptor
        if header is not UNSET:
            field_dict["header"] = header
        if metadata is not UNSET:
            field_dict["metadata"] = metadata
        if relations is not UNSET:
            field_dict["relations"] = relations
        if request_id is not UNSET:
            field_dict["request_id"] = request_id

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.app_update_graph_concept import AppUpdateGraphConcept
        from ..models.app_update_graph_header import AppUpdateGraphHeader
        from ..models.app_update_graph_relation import AppUpdateGraphRelation
        from ..models.app_update_graph_request_metadata import AppUpdateGraphRequestMetadata

        d = dict(src_dict)
        _concepts = d.pop("concepts", UNSET)
        concepts: list[AppUpdateGraphConcept] | Unset = UNSET
        if _concepts is not UNSET:
            concepts = []
            for concepts_item_data in _concepts:
                concepts_item = AppUpdateGraphConcept.from_dict(concepts_item_data)

                concepts.append(concepts_item)

        descriptor = d.pop("descriptor", UNSET)

        _header = d.pop("header", UNSET)
        header: AppUpdateGraphHeader | Unset
        if isinstance(_header, Unset):
            header = UNSET
        else:
            header = AppUpdateGraphHeader.from_dict(_header)

        _metadata = d.pop("metadata", UNSET)
        metadata: AppUpdateGraphRequestMetadata | Unset
        if isinstance(_metadata, Unset):
            metadata = UNSET
        else:
            metadata = AppUpdateGraphRequestMetadata.from_dict(_metadata)

        _relations = d.pop("relations", UNSET)
        relations: list[AppUpdateGraphRelation] | Unset = UNSET
        if _relations is not UNSET:
            relations = []
            for relations_item_data in _relations:
                relations_item = AppUpdateGraphRelation.from_dict(relations_item_data)

                relations.append(relations_item)

        request_id = d.pop("request_id", UNSET)

        app_update_graph_request = cls(
            concepts=concepts,
            descriptor=descriptor,
            header=header,
            metadata=metadata,
            relations=relations,
            request_id=request_id,
        )

        app_update_graph_request.additional_properties = d
        return app_update_graph_request

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
