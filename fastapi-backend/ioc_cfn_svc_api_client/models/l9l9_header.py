from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, TypeVar

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..models.l9_kind import L9Kind
from ..types import UNSET, Unset

if TYPE_CHECKING:
    from ..models.l9_participant_set import L9ParticipantSet
    from ..models.l9l9_header_attributes import L9L9HeaderAttributes
    from ..models.l9l9_header_context import L9L9HeaderContext
    from ..models.l9l9_header_message import L9L9HeaderMessage
    from ..models.l9l9_header_policy import L9L9HeaderPolicy


T = TypeVar("T", bound="L9L9Header")


@_attrs_define
class L9L9Header:
    """
    Attributes:
        attributes (L9L9HeaderAttributes | Unset):
        context (L9L9HeaderContext | Unset):
        kind (L9Kind | Unset):
        message (L9L9HeaderMessage | Unset):
        participants (L9ParticipantSet | Unset):
        policy (L9L9HeaderPolicy | Unset):
        protocol (str | Unset): Protocol corresponds to the JSON schema field "protocol".
        subkind (Any | Unset): Subkind corresponds to the JSON schema field "subkind".
        subprotocol (str | Unset): Subprotocol corresponds to the JSON schema field "subprotocol".
        version (str | Unset): Version corresponds to the JSON schema field "version".
    """

    attributes: L9L9HeaderAttributes | Unset = UNSET
    context: L9L9HeaderContext | Unset = UNSET
    kind: L9Kind | Unset = UNSET
    message: L9L9HeaderMessage | Unset = UNSET
    participants: L9ParticipantSet | Unset = UNSET
    policy: L9L9HeaderPolicy | Unset = UNSET
    protocol: str | Unset = UNSET
    subkind: Any | Unset = UNSET
    subprotocol: str | Unset = UNSET
    version: str | Unset = UNSET
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        attributes: dict[str, Any] | Unset = UNSET
        if not isinstance(self.attributes, Unset):
            attributes = self.attributes.to_dict()

        context: dict[str, Any] | Unset = UNSET
        if not isinstance(self.context, Unset):
            context = self.context.to_dict()

        kind: str | Unset = UNSET
        if not isinstance(self.kind, Unset):
            kind = self.kind.value

        message: dict[str, Any] | Unset = UNSET
        if not isinstance(self.message, Unset):
            message = self.message.to_dict()

        participants: dict[str, Any] | Unset = UNSET
        if not isinstance(self.participants, Unset):
            participants = self.participants.to_dict()

        policy: dict[str, Any] | Unset = UNSET
        if not isinstance(self.policy, Unset):
            policy = self.policy.to_dict()

        protocol = self.protocol

        subkind = self.subkind

        subprotocol = self.subprotocol

        version = self.version

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update({})
        if attributes is not UNSET:
            field_dict["attributes"] = attributes
        if context is not UNSET:
            field_dict["context"] = context
        if kind is not UNSET:
            field_dict["kind"] = kind
        if message is not UNSET:
            field_dict["message"] = message
        if participants is not UNSET:
            field_dict["participants"] = participants
        if policy is not UNSET:
            field_dict["policy"] = policy
        if protocol is not UNSET:
            field_dict["protocol"] = protocol
        if subkind is not UNSET:
            field_dict["subkind"] = subkind
        if subprotocol is not UNSET:
            field_dict["subprotocol"] = subprotocol
        if version is not UNSET:
            field_dict["version"] = version

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.l9_participant_set import L9ParticipantSet
        from ..models.l9l9_header_attributes import L9L9HeaderAttributes
        from ..models.l9l9_header_context import L9L9HeaderContext
        from ..models.l9l9_header_message import L9L9HeaderMessage
        from ..models.l9l9_header_policy import L9L9HeaderPolicy

        d = dict(src_dict)
        _attributes = d.pop("attributes", UNSET)
        attributes: L9L9HeaderAttributes | Unset
        if isinstance(_attributes, Unset):
            attributes = UNSET
        else:
            attributes = L9L9HeaderAttributes.from_dict(_attributes)

        _context = d.pop("context", UNSET)
        context: L9L9HeaderContext | Unset
        if isinstance(_context, Unset):
            context = UNSET
        else:
            context = L9L9HeaderContext.from_dict(_context)

        _kind = d.pop("kind", UNSET)
        kind: L9Kind | Unset
        if isinstance(_kind, Unset):
            kind = UNSET
        else:
            kind = L9Kind(_kind)

        _message = d.pop("message", UNSET)
        message: L9L9HeaderMessage | Unset
        if isinstance(_message, Unset):
            message = UNSET
        else:
            message = L9L9HeaderMessage.from_dict(_message)

        _participants = d.pop("participants", UNSET)
        participants: L9ParticipantSet | Unset
        if isinstance(_participants, Unset):
            participants = UNSET
        else:
            participants = L9ParticipantSet.from_dict(_participants)

        _policy = d.pop("policy", UNSET)
        policy: L9L9HeaderPolicy | Unset
        if isinstance(_policy, Unset):
            policy = UNSET
        else:
            policy = L9L9HeaderPolicy.from_dict(_policy)

        protocol = d.pop("protocol", UNSET)

        subkind = d.pop("subkind", UNSET)

        subprotocol = d.pop("subprotocol", UNSET)

        version = d.pop("version", UNSET)

        l9l9_header = cls(
            attributes=attributes,
            context=context,
            kind=kind,
            message=message,
            participants=participants,
            policy=policy,
            protocol=protocol,
            subkind=subkind,
            subprotocol=subprotocol,
            version=version,
        )

        l9l9_header.additional_properties = d
        return l9l9_header

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
