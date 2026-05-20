from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, TypeVar, cast

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

if TYPE_CHECKING:
    from ..models.context_file import ContextFile


T = TypeVar("T", bound="ParticipantCreate")


@_attrs_define
class ParticipantCreate:
    """
    Attributes:
        agent_handle (str): Agent handle joining the room
        context_files (list[ContextFile] | None | Unset): Files explicitly shared into the session at join time. Visible
            to other participants and forwarded to KXP.
        intent (None | str | Unset): Agent's requirements/intent for coordination
    """

    agent_handle: str
    context_files: list[ContextFile] | None | Unset = UNSET
    intent: None | str | Unset = UNSET
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        agent_handle = self.agent_handle

        context_files: list[dict[str, Any]] | None | Unset
        if isinstance(self.context_files, Unset):
            context_files = UNSET
        elif isinstance(self.context_files, list):
            context_files = []
            for context_files_type_0_item_data in self.context_files:
                context_files_type_0_item = context_files_type_0_item_data.to_dict()
                context_files.append(context_files_type_0_item)

        else:
            context_files = self.context_files

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
        if context_files is not UNSET:
            field_dict["context_files"] = context_files
        if intent is not UNSET:
            field_dict["intent"] = intent

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.context_file import ContextFile

        d = dict(src_dict)
        agent_handle = d.pop("agent_handle")

        def _parse_context_files(data: object) -> list[ContextFile] | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            try:
                if not isinstance(data, list):
                    raise TypeError()
                context_files_type_0 = []
                _context_files_type_0 = data
                for context_files_type_0_item_data in _context_files_type_0:
                    context_files_type_0_item = ContextFile.from_dict(context_files_type_0_item_data)

                    context_files_type_0.append(context_files_type_0_item)

                return context_files_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(list[ContextFile] | None | Unset, data)

        context_files = _parse_context_files(d.pop("context_files", UNSET))

        def _parse_intent(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        intent = _parse_intent(d.pop("intent", UNSET))

        participant_create = cls(
            agent_handle=agent_handle,
            context_files=context_files,
            intent=intent,
        )

        participant_create.additional_properties = d
        return participant_create

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
