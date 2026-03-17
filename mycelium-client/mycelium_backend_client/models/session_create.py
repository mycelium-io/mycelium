from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, cast

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

T = TypeVar("T", bound="SessionCreate")


@_attrs_define
class SessionCreate:
    """
    Attributes:
        agent_handle (str): Agent handle joining the room
        intent (None | str | Unset): Agent's requirements/intent for coordination
    """

    agent_handle: str
    intent: None | str | Unset = UNSET
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        agent_handle = self.agent_handle

        intent: None | str | Unset
        if isinstance(self.intent, Unset):
            intent = UNSET
        else:
            intent = self.intent

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "agent_handle": agent_handle,
            }
        )
        if intent is not UNSET:
            field_dict["intent"] = intent

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        agent_handle = d.pop("agent_handle")

        def _parse_intent(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        intent = _parse_intent(d.pop("intent", UNSET))

        session_create = cls(
            agent_handle=agent_handle,
            intent=intent,
        )

        session_create.additional_properties = d
        return session_create

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
