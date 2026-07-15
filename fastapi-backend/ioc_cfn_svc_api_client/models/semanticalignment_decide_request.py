from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, TypeVar

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

if TYPE_CHECKING:
    from ..models.semanticalignment_agent_reply import SemanticalignmentAgentReply


T = TypeVar("T", bound="SemanticalignmentDecideRequest")


@_attrs_define
class SemanticalignmentDecideRequest:
    """
    Attributes:
        agent_replies (list[SemanticalignmentAgentReply] | Unset): AgentReplies contains each agent's reply to the
            current round.
        session_id (str | Unset): SessionID is the session identifier from the /start response.
    """

    agent_replies: list[SemanticalignmentAgentReply] | Unset = UNSET
    session_id: str | Unset = UNSET
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        agent_replies: list[dict[str, Any]] | Unset = UNSET
        if not isinstance(self.agent_replies, Unset):
            agent_replies = []
            for agent_replies_item_data in self.agent_replies:
                agent_replies_item = agent_replies_item_data.to_dict()
                agent_replies.append(agent_replies_item)

        session_id = self.session_id

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update({})
        if agent_replies is not UNSET:
            field_dict["agent_replies"] = agent_replies
        if session_id is not UNSET:
            field_dict["session_id"] = session_id

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.semanticalignment_agent_reply import SemanticalignmentAgentReply

        d = dict(src_dict)
        _agent_replies = d.pop("agent_replies", UNSET)
        agent_replies: list[SemanticalignmentAgentReply] | Unset = UNSET
        if _agent_replies is not UNSET:
            agent_replies = []
            for agent_replies_item_data in _agent_replies:
                agent_replies_item = SemanticalignmentAgentReply.from_dict(agent_replies_item_data)

                agent_replies.append(agent_replies_item)

        session_id = d.pop("session_id", UNSET)

        semanticalignment_decide_request = cls(
            agent_replies=agent_replies,
            session_id=session_id,
        )

        semanticalignment_decide_request.additional_properties = d
        return semanticalignment_decide_request

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
