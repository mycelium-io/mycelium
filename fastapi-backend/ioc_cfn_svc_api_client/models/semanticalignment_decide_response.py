from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, TypeVar, cast

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

if TYPE_CHECKING:
    from ..models.common_token_usage_meta import CommonTokenUsageMeta
    from ..models.semanticalignment_decide_response_final_result import (
        SemanticalignmentDecideResponseFinalResult,
    )
    from ..models.semanticalignment_shared_memory_result import SemanticalignmentSharedMemoryResult


T = TypeVar("T", bound="SemanticalignmentDecideResponse")


@_attrs_define
class SemanticalignmentDecideResponse:
    """
    Attributes:
        final_result (SemanticalignmentDecideResponseFinalResult | Unset): FinalResult holds the terminal negotiation
            envelope when Status is
            "agreed", "broken", or "timeout".
        messages (list[list[int]] | Unset): Messages contains the next round's messages to dispatch to agents.
            Present only when Status is "ongoing". Forward these to each agent's
            callback endpoint, collect their replies, and submit via /decide again.
        meta (CommonTokenUsageMeta | Unset):
        round_ (int | Unset): Round is the round number that was just evaluated.
        session_id (str | Unset): SessionID echoes the session identifier.
        shared_memory (SemanticalignmentSharedMemoryResult | Unset):
        status (str | Unset): Status is "ongoing", "agreed", "broken", or "timeout".
    """

    final_result: SemanticalignmentDecideResponseFinalResult | Unset = UNSET
    messages: list[list[int]] | Unset = UNSET
    meta: CommonTokenUsageMeta | Unset = UNSET
    round_: int | Unset = UNSET
    session_id: str | Unset = UNSET
    shared_memory: SemanticalignmentSharedMemoryResult | Unset = UNSET
    status: str | Unset = UNSET
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        final_result: dict[str, Any] | Unset = UNSET
        if not isinstance(self.final_result, Unset):
            final_result = self.final_result.to_dict()

        messages: list[list[int]] | Unset = UNSET
        if not isinstance(self.messages, Unset):
            messages = []
            for messages_item_data in self.messages:
                messages_item = messages_item_data

                messages.append(messages_item)

        meta: dict[str, Any] | Unset = UNSET
        if not isinstance(self.meta, Unset):
            meta = self.meta.to_dict()

        round_ = self.round_

        session_id = self.session_id

        shared_memory: dict[str, Any] | Unset = UNSET
        if not isinstance(self.shared_memory, Unset):
            shared_memory = self.shared_memory.to_dict()

        status = self.status

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update({})
        if final_result is not UNSET:
            field_dict["final_result"] = final_result
        if messages is not UNSET:
            field_dict["messages"] = messages
        if meta is not UNSET:
            field_dict["meta"] = meta
        if round_ is not UNSET:
            field_dict["round"] = round_
        if session_id is not UNSET:
            field_dict["session_id"] = session_id
        if shared_memory is not UNSET:
            field_dict["shared_memory"] = shared_memory
        if status is not UNSET:
            field_dict["status"] = status

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.common_token_usage_meta import CommonTokenUsageMeta
        from ..models.semanticalignment_decide_response_final_result import (
            SemanticalignmentDecideResponseFinalResult,
        )
        from ..models.semanticalignment_shared_memory_result import (
            SemanticalignmentSharedMemoryResult,
        )

        d = dict(src_dict)
        _final_result = d.pop("final_result", UNSET)
        final_result: SemanticalignmentDecideResponseFinalResult | Unset
        if isinstance(_final_result, Unset):
            final_result = UNSET
        else:
            final_result = SemanticalignmentDecideResponseFinalResult.from_dict(_final_result)

        _messages = d.pop("messages", UNSET)
        messages: list[list[int]] | Unset = UNSET
        if _messages is not UNSET:
            messages = []
            for messages_item_data in _messages:
                messages_item = cast(list[int], messages_item_data)

                messages.append(messages_item)

        _meta = d.pop("meta", UNSET)
        meta: CommonTokenUsageMeta | Unset
        if isinstance(_meta, Unset):
            meta = UNSET
        else:
            meta = CommonTokenUsageMeta.from_dict(_meta)

        round_ = d.pop("round", UNSET)

        session_id = d.pop("session_id", UNSET)

        _shared_memory = d.pop("shared_memory", UNSET)
        shared_memory: SemanticalignmentSharedMemoryResult | Unset
        if isinstance(_shared_memory, Unset):
            shared_memory = UNSET
        else:
            shared_memory = SemanticalignmentSharedMemoryResult.from_dict(_shared_memory)

        status = d.pop("status", UNSET)

        semanticalignment_decide_response = cls(
            final_result=final_result,
            messages=messages,
            meta=meta,
            round_=round_,
            session_id=session_id,
            shared_memory=shared_memory,
            status=status,
        )

        semanticalignment_decide_response.additional_properties = d
        return semanticalignment_decide_response

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
