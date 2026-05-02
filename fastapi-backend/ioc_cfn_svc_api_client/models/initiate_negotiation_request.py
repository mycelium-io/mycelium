from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, TypeVar, cast

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

if TYPE_CHECKING:
    from ..models.agent import Agent


T = TypeVar("T", bound="InitiateNegotiationRequest")


@_attrs_define
class InitiateNegotiationRequest:
    """Request body to start a new semantic negotiation session.

    Attributes:
        session_id (str):
        content_text (str):
        agents (list[Agent]):
        n_steps (int | None | Unset):  Default: 20.
    """

    session_id: str
    content_text: str
    agents: list[Agent]
    n_steps: int | None | Unset = 20
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        session_id = self.session_id

        content_text = self.content_text

        agents = []
        for agents_item_data in self.agents:
            agents_item = agents_item_data.to_dict()
            agents.append(agents_item)

        n_steps: int | None | Unset
        if isinstance(self.n_steps, Unset):
            n_steps = UNSET
        else:
            n_steps = self.n_steps

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "session_id": session_id,
                "content_text": content_text,
                "agents": agents,
            }
        )
        if n_steps is not UNSET:
            field_dict["n_steps"] = n_steps

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.agent import Agent

        d = dict(src_dict)
        session_id = d.pop("session_id")

        content_text = d.pop("content_text")

        agents = []
        _agents = d.pop("agents")
        for agents_item_data in _agents:
            agents_item = Agent.from_dict(agents_item_data)

            agents.append(agents_item)

        def _parse_n_steps(data: object) -> int | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(int | None | Unset, data)

        n_steps = _parse_n_steps(d.pop("n_steps", UNSET))

        initiate_negotiation_request = cls(
            session_id=session_id,
            content_text=content_text,
            agents=agents,
            n_steps=n_steps,
        )

        initiate_negotiation_request.additional_properties = d
        return initiate_negotiation_request

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
