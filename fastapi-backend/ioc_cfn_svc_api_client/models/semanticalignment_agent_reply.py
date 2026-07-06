from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, TypeVar

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

if TYPE_CHECKING:
    from ..models.semanticalignment_agent_reply_offer import SemanticalignmentAgentReplyOffer


T = TypeVar("T", bound="SemanticalignmentAgentReply")


@_attrs_define
class SemanticalignmentAgentReply:
    """
    Attributes:
        action (str | Unset): Action is one of "accept", "reject", or "counter_offer".
        offer (SemanticalignmentAgentReplyOffer | Unset): Offer is the proposed option per issue when Action is
            "counter_offer".
            Shape: {issue_id: option_label}
        participant_id (str | Unset): ParticipantID is the ID of the agent replying.
    """

    action: str | Unset = UNSET
    offer: SemanticalignmentAgentReplyOffer | Unset = UNSET
    participant_id: str | Unset = UNSET
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        action = self.action

        offer: dict[str, Any] | Unset = UNSET
        if not isinstance(self.offer, Unset):
            offer = self.offer.to_dict()

        participant_id = self.participant_id

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update({})
        if action is not UNSET:
            field_dict["action"] = action
        if offer is not UNSET:
            field_dict["offer"] = offer
        if participant_id is not UNSET:
            field_dict["participant_id"] = participant_id

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.semanticalignment_agent_reply_offer import SemanticalignmentAgentReplyOffer

        d = dict(src_dict)
        action = d.pop("action", UNSET)

        _offer = d.pop("offer", UNSET)
        offer: SemanticalignmentAgentReplyOffer | Unset
        if isinstance(_offer, Unset):
            offer = UNSET
        else:
            offer = SemanticalignmentAgentReplyOffer.from_dict(_offer)

        participant_id = d.pop("participant_id", UNSET)

        semanticalignment_agent_reply = cls(
            action=action,
            offer=offer,
            participant_id=participant_id,
        )

        semanticalignment_agent_reply.additional_properties = d
        return semanticalignment_agent_reply

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
