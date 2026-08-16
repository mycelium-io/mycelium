from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, TypeVar, cast

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

if TYPE_CHECKING:
    from ..models.l9_context_read import L9ContextRead
    from ..models.l9_message_ref import L9MessageRef
    from ..models.l9_participants_read import L9ParticipantsRead


T = TypeVar("T", bound="L9HeaderRead")


@_attrs_define
class L9HeaderRead:
    """
    Attributes:
        kind (str):
        protocol (None | str | Unset):
        subprotocol (None | str | Unset):
        version (None | str | Unset):
        subkind (None | str | Unset):
        participants (L9ParticipantsRead | None | Unset):
        message (L9MessageRef | None | Unset):
        context (L9ContextRead | None | Unset):
    """

    kind: str
    protocol: None | str | Unset = UNSET
    subprotocol: None | str | Unset = UNSET
    version: None | str | Unset = UNSET
    subkind: None | str | Unset = UNSET
    participants: L9ParticipantsRead | None | Unset = UNSET
    message: L9MessageRef | None | Unset = UNSET
    context: L9ContextRead | None | Unset = UNSET
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        from ..models.l9_context_read import L9ContextRead
        from ..models.l9_message_ref import L9MessageRef
        from ..models.l9_participants_read import L9ParticipantsRead

        kind = self.kind

        protocol: None | str | Unset
        if isinstance(self.protocol, Unset):
            protocol = UNSET
        else:
            protocol = self.protocol

        subprotocol: None | str | Unset
        if isinstance(self.subprotocol, Unset):
            subprotocol = UNSET
        else:
            subprotocol = self.subprotocol

        version: None | str | Unset
        if isinstance(self.version, Unset):
            version = UNSET
        else:
            version = self.version

        subkind: None | str | Unset
        if isinstance(self.subkind, Unset):
            subkind = UNSET
        else:
            subkind = self.subkind

        participants: dict[str, Any] | None | Unset
        if isinstance(self.participants, Unset):
            participants = UNSET
        elif isinstance(self.participants, L9ParticipantsRead):
            participants = self.participants.to_dict()
        else:
            participants = self.participants

        message: dict[str, Any] | None | Unset
        if isinstance(self.message, Unset):
            message = UNSET
        elif isinstance(self.message, L9MessageRef):
            message = self.message.to_dict()
        else:
            message = self.message

        context: dict[str, Any] | None | Unset
        if isinstance(self.context, Unset):
            context = UNSET
        elif isinstance(self.context, L9ContextRead):
            context = self.context.to_dict()
        else:
            context = self.context

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "kind": kind,
            }
        )
        if protocol is not UNSET:
            field_dict["protocol"] = protocol
        if subprotocol is not UNSET:
            field_dict["subprotocol"] = subprotocol
        if version is not UNSET:
            field_dict["version"] = version
        if subkind is not UNSET:
            field_dict["subkind"] = subkind
        if participants is not UNSET:
            field_dict["participants"] = participants
        if message is not UNSET:
            field_dict["message"] = message
        if context is not UNSET:
            field_dict["context"] = context

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.l9_context_read import L9ContextRead
        from ..models.l9_message_ref import L9MessageRef
        from ..models.l9_participants_read import L9ParticipantsRead

        d = dict(src_dict)
        kind = d.pop("kind")

        def _parse_protocol(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        protocol = _parse_protocol(d.pop("protocol", UNSET))

        def _parse_subprotocol(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        subprotocol = _parse_subprotocol(d.pop("subprotocol", UNSET))

        def _parse_version(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        version = _parse_version(d.pop("version", UNSET))

        def _parse_subkind(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        subkind = _parse_subkind(d.pop("subkind", UNSET))

        def _parse_participants(data: object) -> L9ParticipantsRead | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            try:
                if not isinstance(data, dict):
                    raise TypeError()
                participants_type_0 = L9ParticipantsRead.from_dict(data)

                return participants_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(L9ParticipantsRead | None | Unset, data)

        participants = _parse_participants(d.pop("participants", UNSET))

        def _parse_message(data: object) -> L9MessageRef | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            try:
                if not isinstance(data, dict):
                    raise TypeError()
                message_type_0 = L9MessageRef.from_dict(data)

                return message_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(L9MessageRef | None | Unset, data)

        message = _parse_message(d.pop("message", UNSET))

        def _parse_context(data: object) -> L9ContextRead | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            try:
                if not isinstance(data, dict):
                    raise TypeError()
                context_type_0 = L9ContextRead.from_dict(data)

                return context_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(L9ContextRead | None | Unset, data)

        context = _parse_context(d.pop("context", UNSET))

        l9_header_read = cls(
            kind=kind,
            protocol=protocol,
            subprotocol=subprotocol,
            version=version,
            subkind=subkind,
            participants=participants,
            message=message,
            context=context,
        )

        l9_header_read.additional_properties = d
        return l9_header_read

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
