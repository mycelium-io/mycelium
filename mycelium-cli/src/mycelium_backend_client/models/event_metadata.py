from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, TypeVar, cast

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..models.event_metadata_status_type_0 import EventMetadataStatusType0
from ..types import UNSET, Unset

if TYPE_CHECKING:
    from ..models.event_metadata_payload import EventMetadataPayload
    from ..models.event_provenance_ref import EventProvenanceRef


T = TypeVar("T", bound="EventMetadata")


@_attrs_define
class EventMetadata:
    """Structured metadata for ``message_type="event"``.

    Retention (``ttl_seconds``) and statefulness (``status``) are independent
    attributes, not distinct message types — one primitive covers a transient
    source-activity feed and a durable status-bearing ledger.

        Attributes:
            kind (str): Event kind (open vocabulary)
            ttl_seconds (int | None | Unset): Retention cap for transient kinds; absent = durable
            status (EventMetadataStatusType0 | None | Unset): Ledger status for stateful kinds; null for stateless
            payload (EventMetadataPayload | Unset): Kind-specific structured data
            provenance (list[EventProvenanceRef] | Unset):
            correlation_id (None | str | Unset): Groups related events / links updates to their origin
    """

    kind: str
    ttl_seconds: int | None | Unset = UNSET
    status: EventMetadataStatusType0 | None | Unset = UNSET
    payload: EventMetadataPayload | Unset = UNSET
    provenance: list[EventProvenanceRef] | Unset = UNSET
    correlation_id: None | str | Unset = UNSET
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        kind = self.kind

        ttl_seconds: int | None | Unset
        if isinstance(self.ttl_seconds, Unset):
            ttl_seconds = UNSET
        else:
            ttl_seconds = self.ttl_seconds

        status: None | str | Unset
        if isinstance(self.status, Unset):
            status = UNSET
        elif isinstance(self.status, EventMetadataStatusType0):
            status = self.status.value
        else:
            status = self.status

        payload: dict[str, Any] | Unset = UNSET
        if not isinstance(self.payload, Unset):
            payload = self.payload.to_dict()

        provenance: list[dict[str, Any]] | Unset = UNSET
        if not isinstance(self.provenance, Unset):
            provenance = []
            for provenance_item_data in self.provenance:
                provenance_item = provenance_item_data.to_dict()
                provenance.append(provenance_item)

        correlation_id: None | str | Unset
        if isinstance(self.correlation_id, Unset):
            correlation_id = UNSET
        else:
            correlation_id = self.correlation_id

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "kind": kind,
            }
        )
        if ttl_seconds is not UNSET:
            field_dict["ttl_seconds"] = ttl_seconds
        if status is not UNSET:
            field_dict["status"] = status
        if payload is not UNSET:
            field_dict["payload"] = payload
        if provenance is not UNSET:
            field_dict["provenance"] = provenance
        if correlation_id is not UNSET:
            field_dict["correlation_id"] = correlation_id

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.event_metadata_payload import EventMetadataPayload
        from ..models.event_provenance_ref import EventProvenanceRef

        d = dict(src_dict)
        kind = d.pop("kind")

        def _parse_ttl_seconds(data: object) -> int | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(int | None | Unset, data)

        ttl_seconds = _parse_ttl_seconds(d.pop("ttl_seconds", UNSET))

        def _parse_status(data: object) -> EventMetadataStatusType0 | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            try:
                if not isinstance(data, str):
                    raise TypeError()
                status_type_0 = EventMetadataStatusType0(data)

                return status_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(EventMetadataStatusType0 | None | Unset, data)

        status = _parse_status(d.pop("status", UNSET))

        _payload = d.pop("payload", UNSET)
        payload: EventMetadataPayload | Unset
        if isinstance(_payload, Unset):
            payload = UNSET
        else:
            payload = EventMetadataPayload.from_dict(_payload)

        _provenance = d.pop("provenance", UNSET)
        provenance: list[EventProvenanceRef] | Unset = UNSET
        if _provenance is not UNSET:
            provenance = []
            for provenance_item_data in _provenance:
                provenance_item = EventProvenanceRef.from_dict(provenance_item_data)

                provenance.append(provenance_item)

        def _parse_correlation_id(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        correlation_id = _parse_correlation_id(d.pop("correlation_id", UNSET))

        event_metadata = cls(
            kind=kind,
            ttl_seconds=ttl_seconds,
            status=status,
            payload=payload,
            provenance=provenance,
            correlation_id=correlation_id,
        )

        event_metadata.additional_properties = d
        return event_metadata

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
