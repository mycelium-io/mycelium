from __future__ import annotations

import datetime
from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, TypeVar, cast
from uuid import UUID

from attrs import define as _attrs_define
from attrs import field as _attrs_field
from dateutil.parser import isoparse

from ..types import UNSET, Unset

if TYPE_CHECKING:
    from ..models.context_file_read import ContextFileRead


T = TypeVar("T", bound="ParticipantRead")


@_attrs_define
class ParticipantRead:
    """
    Attributes:
        id (UUID):
        coordination_session_id (UUID):
        agent_handle (str):
        joined_at (datetime.datetime):
        intent (None | str | Unset):
        last_seen (datetime.datetime | None | Unset):
        context_files (list[ContextFileRead] | None | Unset):
    """

    id: UUID
    coordination_session_id: UUID
    agent_handle: str
    joined_at: datetime.datetime
    intent: None | str | Unset = UNSET
    last_seen: datetime.datetime | None | Unset = UNSET
    context_files: list[ContextFileRead] | None | Unset = UNSET
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        id = str(self.id)

        coordination_session_id = str(self.coordination_session_id)

        agent_handle = self.agent_handle

        joined_at = self.joined_at.isoformat()

        intent: None | str | Unset
        if isinstance(self.intent, Unset):
            intent = UNSET
        else:
            intent = self.intent

        last_seen: None | str | Unset
        if isinstance(self.last_seen, Unset):
            last_seen = UNSET
        elif isinstance(self.last_seen, datetime.datetime):
            last_seen = self.last_seen.isoformat()
        else:
            last_seen = self.last_seen

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

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "id": id,
                "coordination_session_id": coordination_session_id,
                "agent_handle": agent_handle,
                "joined_at": joined_at,
            }
        )
        if intent is not UNSET:
            field_dict["intent"] = intent
        if last_seen is not UNSET:
            field_dict["last_seen"] = last_seen
        if context_files is not UNSET:
            field_dict["context_files"] = context_files

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.context_file_read import ContextFileRead

        d = dict(src_dict)
        id = UUID(d.pop("id"))

        coordination_session_id = UUID(d.pop("coordination_session_id"))

        agent_handle = d.pop("agent_handle")

        joined_at = isoparse(d.pop("joined_at"))

        def _parse_intent(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        intent = _parse_intent(d.pop("intent", UNSET))

        def _parse_last_seen(data: object) -> datetime.datetime | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            try:
                if not isinstance(data, str):
                    raise TypeError()
                last_seen_type_0 = isoparse(data)

                return last_seen_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(datetime.datetime | None | Unset, data)

        last_seen = _parse_last_seen(d.pop("last_seen", UNSET))

        def _parse_context_files(data: object) -> list[ContextFileRead] | None | Unset:
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
                    context_files_type_0_item = ContextFileRead.from_dict(context_files_type_0_item_data)

                    context_files_type_0.append(context_files_type_0_item)

                return context_files_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(list[ContextFileRead] | None | Unset, data)

        context_files = _parse_context_files(d.pop("context_files", UNSET))

        participant_read = cls(
            id=id,
            coordination_session_id=coordination_session_id,
            agent_handle=agent_handle,
            joined_at=joined_at,
            intent=intent,
            last_seen=last_seen,
            context_files=context_files,
        )

        participant_read.additional_properties = d
        return participant_read

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
