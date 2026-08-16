from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, TypeVar, cast

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

if TYPE_CHECKING:
    from ..models.l9_header_read import L9HeaderRead
    from ..models.l9_payload_read import L9PayloadRead


T = TypeVar("T", bound="L9EnvelopeRead")


@_attrs_define
class L9EnvelopeRead:
    """One faithful L9 envelope in an episode's causal chain.

    The sender is the first actor (`header.participants.actors[0].id`) by the
    bus convention in `app.services.l9`; there is deliberately no flattened
    `sender_handle` on the wire envelope — the frontend derives it from actors.

        Attributes:
            header (L9HeaderRead):
            payload (L9PayloadRead | None | Unset):
    """

    header: L9HeaderRead
    payload: L9PayloadRead | None | Unset = UNSET
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        from ..models.l9_payload_read import L9PayloadRead

        header = self.header.to_dict()

        payload: dict[str, Any] | None | Unset
        if isinstance(self.payload, Unset):
            payload = UNSET
        elif isinstance(self.payload, L9PayloadRead):
            payload = self.payload.to_dict()
        else:
            payload = self.payload

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "header": header,
            }
        )
        if payload is not UNSET:
            field_dict["payload"] = payload

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.l9_header_read import L9HeaderRead
        from ..models.l9_payload_read import L9PayloadRead

        d = dict(src_dict)
        header = L9HeaderRead.from_dict(d.pop("header"))

        def _parse_payload(data: object) -> L9PayloadRead | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            try:
                if not isinstance(data, dict):
                    raise TypeError()
                payload_type_0 = L9PayloadRead.from_dict(data)

                return payload_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(L9PayloadRead | None | Unset, data)

        payload = _parse_payload(d.pop("payload", UNSET))

        l9_envelope_read = cls(
            header=header,
            payload=payload,
        )

        l9_envelope_read.additional_properties = d
        return l9_envelope_read

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
