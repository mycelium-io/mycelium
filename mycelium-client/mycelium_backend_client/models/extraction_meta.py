from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

T = TypeVar("T", bound="ExtractionMeta")


@_attrs_define
class ExtractionMeta:
    """
    Attributes:
        records_processed (int | Unset):  Default: 0.
        concepts_extracted (int | Unset):  Default: 0.
        relations_extracted (int | Unset):  Default: 0.
        dedup_enabled (bool | Unset):  Default: False.
        concepts_deduped (int | Unset):  Default: 0.
        relations_deduped (int | Unset):  Default: 0.
    """

    records_processed: int | Unset = 0
    concepts_extracted: int | Unset = 0
    relations_extracted: int | Unset = 0
    dedup_enabled: bool | Unset = False
    concepts_deduped: int | Unset = 0
    relations_deduped: int | Unset = 0
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        records_processed = self.records_processed

        concepts_extracted = self.concepts_extracted

        relations_extracted = self.relations_extracted

        dedup_enabled = self.dedup_enabled

        concepts_deduped = self.concepts_deduped

        relations_deduped = self.relations_deduped

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update({})
        if records_processed is not UNSET:
            field_dict["records_processed"] = records_processed
        if concepts_extracted is not UNSET:
            field_dict["concepts_extracted"] = concepts_extracted
        if relations_extracted is not UNSET:
            field_dict["relations_extracted"] = relations_extracted
        if dedup_enabled is not UNSET:
            field_dict["dedup_enabled"] = dedup_enabled
        if concepts_deduped is not UNSET:
            field_dict["concepts_deduped"] = concepts_deduped
        if relations_deduped is not UNSET:
            field_dict["relations_deduped"] = relations_deduped

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        records_processed = d.pop("records_processed", UNSET)

        concepts_extracted = d.pop("concepts_extracted", UNSET)

        relations_extracted = d.pop("relations_extracted", UNSET)

        dedup_enabled = d.pop("dedup_enabled", UNSET)

        concepts_deduped = d.pop("concepts_deduped", UNSET)

        relations_deduped = d.pop("relations_deduped", UNSET)

        extraction_meta = cls(
            records_processed=records_processed,
            concepts_extracted=concepts_extracted,
            relations_extracted=relations_extracted,
            dedup_enabled=dedup_enabled,
            concepts_deduped=concepts_deduped,
            relations_deduped=relations_deduped,
        )

        extraction_meta.additional_properties = d
        return extraction_meta

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
