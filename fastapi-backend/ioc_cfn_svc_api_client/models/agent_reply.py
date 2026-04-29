from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, TypeVar, cast

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..models.agent_reply_action import AgentReplyAction
from ..types import UNSET, Unset

if TYPE_CHECKING:
    from ..models.agent_reply_offer_type_0 import AgentReplyOfferType0


T = TypeVar("T", bound="AgentReply")


@_attrs_define
class AgentReply:
    """A single agent reply used to advance an existing session.

    Attributes:
        agent_id (str):
        action (AgentReplyAction):
        offer (AgentReplyOfferType0 | None | Unset):
    """

    agent_id: str
    action: AgentReplyAction
    offer: AgentReplyOfferType0 | None | Unset = UNSET
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        from ..models.agent_reply_offer_type_0 import AgentReplyOfferType0

        agent_id = self.agent_id

        action = self.action.value

        offer: dict[str, Any] | None | Unset
        if isinstance(self.offer, Unset):
            offer = UNSET
        elif isinstance(self.offer, AgentReplyOfferType0):
            offer = self.offer.to_dict()
        else:
            offer = self.offer

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "agent_id": agent_id,
                "action": action,
            }
        )
        if offer is not UNSET:
            field_dict["offer"] = offer

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.agent_reply_offer_type_0 import AgentReplyOfferType0

        d = dict(src_dict)
        agent_id = d.pop("agent_id")

        action = AgentReplyAction(d.pop("action"))

        def _parse_offer(data: object) -> AgentReplyOfferType0 | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            try:
                if not isinstance(data, dict):
                    raise TypeError()
                offer_type_0 = AgentReplyOfferType0.from_dict(data)

                return offer_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(AgentReplyOfferType0 | None | Unset, data)

        offer = _parse_offer(d.pop("offer", UNSET))

        agent_reply = cls(
            agent_id=agent_id,
            action=action,
            offer=offer,
        )

        agent_reply.additional_properties = d
        return agent_reply

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
