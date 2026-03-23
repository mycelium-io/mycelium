from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, TypeVar, cast

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

if TYPE_CHECKING:
    from ..models.evidence_payload_metadata import EvidencePayloadMetadata


T = TypeVar("T", bound="EvidencePayload")


@_attrs_define
class EvidencePayload:
    """
    Attributes:
        intent (str):
        metadata (EvidencePayloadMetadata | Unset):
        additional_context (list[Any] | Unset):
    """

    intent: str
    metadata: EvidencePayloadMetadata | Unset = UNSET
    additional_context: list[Any] | Unset = UNSET
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        intent = self.intent

        metadata: dict[str, Any] | Unset = UNSET
        if not isinstance(self.metadata, Unset):
            metadata = self.metadata.to_dict()

        additional_context: list[Any] | Unset = UNSET
        if not isinstance(self.additional_context, Unset):
            additional_context = self.additional_context

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "intent": intent,
            }
        )
        if metadata is not UNSET:
            field_dict["metadata"] = metadata
        if additional_context is not UNSET:
            field_dict["additional_context"] = additional_context

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.evidence_payload_metadata import EvidencePayloadMetadata

        d = dict(src_dict)
        intent = d.pop("intent")

        _metadata = d.pop("metadata", UNSET)
        metadata: EvidencePayloadMetadata | Unset
        if isinstance(_metadata, Unset):
            metadata = UNSET
        else:
            metadata = EvidencePayloadMetadata.from_dict(_metadata)

        additional_context = cast(list[Any], d.pop("additional_context", UNSET))

        evidence_payload = cls(
            intent=intent,
            metadata=metadata,
            additional_context=additional_context,
        )

        evidence_payload.additional_properties = d
        return evidence_payload

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
