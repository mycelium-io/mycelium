from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, cast

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

T = TypeVar("T", bound="AgentContextOut")


@_attrs_define
class AgentContextOut:
    """
    Attributes:
        room (str):
        generated_at (str):
        handle (None | str | Unset):
        context (None | str | Unset):
    """

    room: str
    generated_at: str
    handle: None | str | Unset = UNSET
    context: None | str | Unset = UNSET
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        room = self.room

        generated_at = self.generated_at

        handle: None | str | Unset
        if isinstance(self.handle, Unset):
            handle = UNSET
        else:
            handle = self.handle

        context: None | str | Unset
        if isinstance(self.context, Unset):
            context = UNSET
        else:
            context = self.context

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "room": room,
                "generated_at": generated_at,
            }
        )
        if handle is not UNSET:
            field_dict["handle"] = handle
        if context is not UNSET:
            field_dict["context"] = context

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        room = d.pop("room")

        generated_at = d.pop("generated_at")

        def _parse_handle(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        handle = _parse_handle(d.pop("handle", UNSET))

        def _parse_context(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        context = _parse_context(d.pop("context", UNSET))

        agent_context_out = cls(
            room=room,
            generated_at=generated_at,
            handle=handle,
            context=context,
        )

        agent_context_out.additional_properties = d
        return agent_context_out

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
