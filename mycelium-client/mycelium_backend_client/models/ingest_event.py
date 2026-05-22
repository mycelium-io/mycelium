from __future__ import annotations

import datetime
from collections.abc import Mapping
from typing import Any, TypeVar, cast

from attrs import define as _attrs_define
from attrs import field as _attrs_field
from dateutil.parser import isoparse

from ..models.ingest_event_state import IngestEventState
from ..types import UNSET, Unset

T = TypeVar("T", bound="IngestEvent")


@_attrs_define
class IngestEvent:
    """A single CFN shared-memories forward attempt, one of:

    - ``ok``        — forwarded to CFN successfully
    - ``deduped``   — hash matched in-process cache, returned prior response_id
    - ``truncated`` — forwarded OK, but the hook capped tool-call content
    - ``refused``   — refused locally (circuit breaker above max_input_tokens)
    - ``disabled``  — master switch off, accepted and discarded
    - ``error``     — CFN returned non-2xx or was unreachable

        Attributes:
            estimated_cfn_knowledge_input_tokens (int):
            latency_ms (float):
            mas_id (str):
            payload_bytes (int):
            record_count (int):
            request_id (str):
            timestamp (datetime.datetime):
            workspace_id (str):
            agent_id (None | str | Unset):
            cfn_message (None | str | Unset):
            cfn_status (int | None | Unset):
            reason (None | str | Unset):
            state (IngestEventState | Unset):  Default: IngestEventState.OK.
    """

    estimated_cfn_knowledge_input_tokens: int
    latency_ms: float
    mas_id: str
    payload_bytes: int
    record_count: int
    request_id: str
    timestamp: datetime.datetime
    workspace_id: str
    agent_id: None | str | Unset = UNSET
    cfn_message: None | str | Unset = UNSET
    cfn_status: int | None | Unset = UNSET
    reason: None | str | Unset = UNSET
    state: IngestEventState | Unset = IngestEventState.OK
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        estimated_cfn_knowledge_input_tokens = self.estimated_cfn_knowledge_input_tokens

        latency_ms = self.latency_ms

        mas_id = self.mas_id

        payload_bytes = self.payload_bytes

        record_count = self.record_count

        request_id = self.request_id

        timestamp = self.timestamp.isoformat()

        workspace_id = self.workspace_id

        agent_id: None | str | Unset
        if isinstance(self.agent_id, Unset):
            agent_id = UNSET
        else:
            agent_id = self.agent_id

        cfn_message: None | str | Unset
        if isinstance(self.cfn_message, Unset):
            cfn_message = UNSET
        else:
            cfn_message = self.cfn_message

        cfn_status: int | None | Unset
        if isinstance(self.cfn_status, Unset):
            cfn_status = UNSET
        else:
            cfn_status = self.cfn_status

        reason: None | str | Unset
        if isinstance(self.reason, Unset):
            reason = UNSET
        else:
            reason = self.reason

        state: str | Unset = UNSET
        if not isinstance(self.state, Unset):
            state = self.state.value

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "estimated_cfn_knowledge_input_tokens": estimated_cfn_knowledge_input_tokens,
                "latency_ms": latency_ms,
                "mas_id": mas_id,
                "payload_bytes": payload_bytes,
                "record_count": record_count,
                "request_id": request_id,
                "timestamp": timestamp,
                "workspace_id": workspace_id,
            }
        )
        if agent_id is not UNSET:
            field_dict["agent_id"] = agent_id
        if cfn_message is not UNSET:
            field_dict["cfn_message"] = cfn_message
        if cfn_status is not UNSET:
            field_dict["cfn_status"] = cfn_status
        if reason is not UNSET:
            field_dict["reason"] = reason
        if state is not UNSET:
            field_dict["state"] = state

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        estimated_cfn_knowledge_input_tokens = d.pop("estimated_cfn_knowledge_input_tokens")

        latency_ms = d.pop("latency_ms")

        mas_id = d.pop("mas_id")

        payload_bytes = d.pop("payload_bytes")

        record_count = d.pop("record_count")

        request_id = d.pop("request_id")

        timestamp = isoparse(d.pop("timestamp"))

        workspace_id = d.pop("workspace_id")

        def _parse_agent_id(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        agent_id = _parse_agent_id(d.pop("agent_id", UNSET))

        def _parse_cfn_message(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        cfn_message = _parse_cfn_message(d.pop("cfn_message", UNSET))

        def _parse_cfn_status(data: object) -> int | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(int | None | Unset, data)

        cfn_status = _parse_cfn_status(d.pop("cfn_status", UNSET))

        def _parse_reason(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        reason = _parse_reason(d.pop("reason", UNSET))

        _state = d.pop("state", UNSET)
        state: IngestEventState | Unset
        if isinstance(_state, Unset):
            state = UNSET
        else:
            state = IngestEventState(_state)

        ingest_event = cls(
            estimated_cfn_knowledge_input_tokens=estimated_cfn_knowledge_input_tokens,
            latency_ms=latency_ms,
            mas_id=mas_id,
            payload_bytes=payload_bytes,
            record_count=record_count,
            request_id=request_id,
            timestamp=timestamp,
            workspace_id=workspace_id,
            agent_id=agent_id,
            cfn_message=cfn_message,
            cfn_status=cfn_status,
            reason=reason,
            state=state,
        )

        ingest_event.additional_properties = d
        return ingest_event

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
