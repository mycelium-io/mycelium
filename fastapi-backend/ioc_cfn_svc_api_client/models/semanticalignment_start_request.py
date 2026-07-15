from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, TypeVar

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

if TYPE_CHECKING:
    from ..models.semanticalignment_agent import SemanticalignmentAgent


T = TypeVar("T", bound="SemanticalignmentStartRequest")


@_attrs_define
class SemanticalignmentStartRequest:
    """
    Attributes:
        agents (list[SemanticalignmentAgent] | Unset): Agents is the list of participating agents (minimum 2).
        content_text (str | Unset): ContentText is the negotiation prompt/context used to initialize the session.
        n_steps (int | Unset): NSteps is the maximum number of SAO rounds.
            If omitted, the service computes a budget from negotiation complexity.
        session_id (str | Unset): SessionID is the client-provided session identifier.
    """

    agents: list[SemanticalignmentAgent] | Unset = UNSET
    content_text: str | Unset = UNSET
    n_steps: int | Unset = UNSET
    session_id: str | Unset = UNSET
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        agents: list[dict[str, Any]] | Unset = UNSET
        if not isinstance(self.agents, Unset):
            agents = []
            for agents_item_data in self.agents:
                agents_item = agents_item_data.to_dict()
                agents.append(agents_item)

        content_text = self.content_text

        n_steps = self.n_steps

        session_id = self.session_id

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update({})
        if agents is not UNSET:
            field_dict["agents"] = agents
        if content_text is not UNSET:
            field_dict["content_text"] = content_text
        if n_steps is not UNSET:
            field_dict["n_steps"] = n_steps
        if session_id is not UNSET:
            field_dict["session_id"] = session_id

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.semanticalignment_agent import SemanticalignmentAgent

        d = dict(src_dict)
        _agents = d.pop("agents", UNSET)
        agents: list[SemanticalignmentAgent] | Unset = UNSET
        if _agents is not UNSET:
            agents = []
            for agents_item_data in _agents:
                agents_item = SemanticalignmentAgent.from_dict(agents_item_data)

                agents.append(agents_item)

        content_text = d.pop("content_text", UNSET)

        n_steps = d.pop("n_steps", UNSET)

        session_id = d.pop("session_id", UNSET)

        semanticalignment_start_request = cls(
            agents=agents,
            content_text=content_text,
            n_steps=n_steps,
            session_id=session_id,
        )

        semanticalignment_start_request.additional_properties = d
        return semanticalignment_start_request

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
