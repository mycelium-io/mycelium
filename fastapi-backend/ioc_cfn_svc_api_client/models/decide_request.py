from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, TypeVar

from attrs import define as _attrs_define
from attrs import field as _attrs_field

if TYPE_CHECKING:
    from ..models.agent_reply import AgentReply


T = TypeVar("T", bound="DecideRequest")


@_attrs_define
class DecideRequest:
    """Request body to advance an existing semantic negotiation session.

    Attributes:
        session_id (str):
        agent_replies (list[AgentReply]):
    """

    session_id: str
    agent_replies: list[AgentReply]
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        session_id = self.session_id

        agent_replies = []
        for agent_replies_item_data in self.agent_replies:
            agent_replies_item = agent_replies_item_data.to_dict()
            agent_replies.append(agent_replies_item)

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "session_id": session_id,
                "agent_replies": agent_replies,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.agent_reply import AgentReply

        d = dict(src_dict)
        session_id = d.pop("session_id")

        agent_replies = []
        _agent_replies = d.pop("agent_replies")
        for agent_replies_item_data in _agent_replies:
            agent_replies_item = AgentReply.from_dict(agent_replies_item_data)

            agent_replies.append(agent_replies_item)

        decide_request = cls(
            session_id=session_id,
            agent_replies=agent_replies,
        )

        decide_request.additional_properties = d
        return decide_request

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
