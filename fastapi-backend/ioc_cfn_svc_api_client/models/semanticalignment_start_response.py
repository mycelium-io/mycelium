from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, TypeVar, cast

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

if TYPE_CHECKING:
    from ..models.common_token_usage_meta import CommonTokenUsageMeta
    from ..models.semanticalignment_negotiation_trace import SemanticalignmentNegotiationTrace
    from ..models.semanticalignment_round_offer import SemanticalignmentRoundOffer
    from ..models.semanticalignment_start_response_options_per_issue import (
        SemanticalignmentStartResponseOptionsPerIssue,
    )


T = TypeVar("T", bound="SemanticalignmentStartResponse")


@_attrs_define
class SemanticalignmentStartResponse:
    """
    Attributes:
        current_round (SemanticalignmentRoundOffer | Unset):
        issues (list[str] | Unset): Issues is the list of negotiable issues discovered from content_text.
        messages (list[list[int]] | Unset): Messages contains the first round's messages to dispatch to agents.
            Forward each message to the corresponding agent's callback endpoint,
            collect their replies, and submit via /decide.
        meta (CommonTokenUsageMeta | Unset):
        n_steps (int | Unset): NSteps is the SAO round budget for this session.
        options_per_issue (SemanticalignmentStartResponseOptionsPerIssue | Unset): OptionsPerIssue lists the candidate
            options for each issue.
        round_ (int | Unset): Round is the current round number (1-based).
        session_id (str | Unset): SessionID echoes the session identifier.
        status (str | Unset): Status is "initiated", "ongoing", "agreed", "broken", or "timeout".
        total_rounds (int | Unset): TotalRounds is the total SAO rounds in the pre-computed trace (SSTP envelope path
            only).
        trace (SemanticalignmentNegotiationTrace | Unset):
    """

    current_round: SemanticalignmentRoundOffer | Unset = UNSET
    issues: list[str] | Unset = UNSET
    messages: list[list[int]] | Unset = UNSET
    meta: CommonTokenUsageMeta | Unset = UNSET
    n_steps: int | Unset = UNSET
    options_per_issue: SemanticalignmentStartResponseOptionsPerIssue | Unset = UNSET
    round_: int | Unset = UNSET
    session_id: str | Unset = UNSET
    status: str | Unset = UNSET
    total_rounds: int | Unset = UNSET
    trace: SemanticalignmentNegotiationTrace | Unset = UNSET
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        current_round: dict[str, Any] | Unset = UNSET
        if not isinstance(self.current_round, Unset):
            current_round = self.current_round.to_dict()

        issues: list[str] | Unset = UNSET
        if not isinstance(self.issues, Unset):
            issues = self.issues

        messages: list[list[int]] | Unset = UNSET
        if not isinstance(self.messages, Unset):
            messages = []
            for messages_item_data in self.messages:
                messages_item = messages_item_data

                messages.append(messages_item)

        meta: dict[str, Any] | Unset = UNSET
        if not isinstance(self.meta, Unset):
            meta = self.meta.to_dict()

        n_steps = self.n_steps

        options_per_issue: dict[str, Any] | Unset = UNSET
        if not isinstance(self.options_per_issue, Unset):
            options_per_issue = self.options_per_issue.to_dict()

        round_ = self.round_

        session_id = self.session_id

        status = self.status

        total_rounds = self.total_rounds

        trace: dict[str, Any] | Unset = UNSET
        if not isinstance(self.trace, Unset):
            trace = self.trace.to_dict()

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update({})
        if current_round is not UNSET:
            field_dict["current_round"] = current_round
        if issues is not UNSET:
            field_dict["issues"] = issues
        if messages is not UNSET:
            field_dict["messages"] = messages
        if meta is not UNSET:
            field_dict["meta"] = meta
        if n_steps is not UNSET:
            field_dict["n_steps"] = n_steps
        if options_per_issue is not UNSET:
            field_dict["options_per_issue"] = options_per_issue
        if round_ is not UNSET:
            field_dict["round"] = round_
        if session_id is not UNSET:
            field_dict["session_id"] = session_id
        if status is not UNSET:
            field_dict["status"] = status
        if total_rounds is not UNSET:
            field_dict["total_rounds"] = total_rounds
        if trace is not UNSET:
            field_dict["trace"] = trace

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.common_token_usage_meta import CommonTokenUsageMeta
        from ..models.semanticalignment_negotiation_trace import SemanticalignmentNegotiationTrace
        from ..models.semanticalignment_round_offer import SemanticalignmentRoundOffer
        from ..models.semanticalignment_start_response_options_per_issue import (
            SemanticalignmentStartResponseOptionsPerIssue,
        )

        d = dict(src_dict)
        _current_round = d.pop("current_round", UNSET)
        current_round: SemanticalignmentRoundOffer | Unset
        if isinstance(_current_round, Unset):
            current_round = UNSET
        else:
            current_round = SemanticalignmentRoundOffer.from_dict(_current_round)

        issues = cast(list[str], d.pop("issues", UNSET))

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

        n_steps = d.pop("n_steps", UNSET)

        _options_per_issue = d.pop("options_per_issue", UNSET)
        options_per_issue: SemanticalignmentStartResponseOptionsPerIssue | Unset
        if isinstance(_options_per_issue, Unset):
            options_per_issue = UNSET
        else:
            options_per_issue = SemanticalignmentStartResponseOptionsPerIssue.from_dict(
                _options_per_issue
            )

        round_ = d.pop("round", UNSET)

        session_id = d.pop("session_id", UNSET)

        status = d.pop("status", UNSET)

        total_rounds = d.pop("total_rounds", UNSET)

        _trace = d.pop("trace", UNSET)
        trace: SemanticalignmentNegotiationTrace | Unset
        if isinstance(_trace, Unset):
            trace = UNSET
        else:
            trace = SemanticalignmentNegotiationTrace.from_dict(_trace)

        semanticalignment_start_response = cls(
            current_round=current_round,
            issues=issues,
            messages=messages,
            meta=meta,
            n_steps=n_steps,
            options_per_issue=options_per_issue,
            round_=round_,
            session_id=session_id,
            status=status,
            total_rounds=total_rounds,
            trace=trace,
        )

        semanticalignment_start_response.additional_properties = d
        return semanticalignment_start_response

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
