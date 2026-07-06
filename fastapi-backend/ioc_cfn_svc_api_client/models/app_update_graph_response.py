from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, TypeVar

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

if TYPE_CHECKING:
    from ..models.app_update_graph_header import AppUpdateGraphHeader
    from ..models.app_update_graph_response_metadata import AppUpdateGraphResponseMetadata


T = TypeVar("T", bound="AppUpdateGraphResponse")


@_attrs_define
class AppUpdateGraphResponse:
    """
    Attributes:
        concepts_updated (int | Unset):
        descriptor (str | Unset):
        error (str | Unset):
        header (AppUpdateGraphHeader | Unset):
        metadata (AppUpdateGraphResponseMetadata | Unset):
        relations_updated (int | Unset):
        response_id (str | Unset):
        updated_at (int | Unset):
    """

    concepts_updated: int | Unset = UNSET
    descriptor: str | Unset = UNSET
    error: str | Unset = UNSET
    header: AppUpdateGraphHeader | Unset = UNSET
    metadata: AppUpdateGraphResponseMetadata | Unset = UNSET
    relations_updated: int | Unset = UNSET
    response_id: str | Unset = UNSET
    updated_at: int | Unset = UNSET
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        concepts_updated = self.concepts_updated

        descriptor = self.descriptor

        error = self.error

        header: dict[str, Any] | Unset = UNSET
        if not isinstance(self.header, Unset):
            header = self.header.to_dict()

        metadata: dict[str, Any] | Unset = UNSET
        if not isinstance(self.metadata, Unset):
            metadata = self.metadata.to_dict()

        relations_updated = self.relations_updated

        response_id = self.response_id

        updated_at = self.updated_at

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update({})
        if concepts_updated is not UNSET:
            field_dict["concepts_updated"] = concepts_updated
        if descriptor is not UNSET:
            field_dict["descriptor"] = descriptor
        if error is not UNSET:
            field_dict["error"] = error
        if header is not UNSET:
            field_dict["header"] = header
        if metadata is not UNSET:
            field_dict["metadata"] = metadata
        if relations_updated is not UNSET:
            field_dict["relations_updated"] = relations_updated
        if response_id is not UNSET:
            field_dict["response_id"] = response_id
        if updated_at is not UNSET:
            field_dict["updated_at"] = updated_at

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.app_update_graph_header import AppUpdateGraphHeader
        from ..models.app_update_graph_response_metadata import AppUpdateGraphResponseMetadata

        d = dict(src_dict)
        concepts_updated = d.pop("concepts_updated", UNSET)

        descriptor = d.pop("descriptor", UNSET)

        error = d.pop("error", UNSET)

        _header = d.pop("header", UNSET)
        header: AppUpdateGraphHeader | Unset
        if isinstance(_header, Unset):
            header = UNSET
        else:
            header = AppUpdateGraphHeader.from_dict(_header)

        _metadata = d.pop("metadata", UNSET)
        metadata: AppUpdateGraphResponseMetadata | Unset
        if isinstance(_metadata, Unset):
            metadata = UNSET
        else:
            metadata = AppUpdateGraphResponseMetadata.from_dict(_metadata)

        relations_updated = d.pop("relations_updated", UNSET)

        response_id = d.pop("response_id", UNSET)

        updated_at = d.pop("updated_at", UNSET)

        app_update_graph_response = cls(
            concepts_updated=concepts_updated,
            descriptor=descriptor,
            error=error,
            header=header,
            metadata=metadata,
            relations_updated=relations_updated,
            response_id=response_id,
            updated_at=updated_at,
        )

        app_update_graph_response.additional_properties = d
        return app_update_graph_response

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
