from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, TypeVar

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

if TYPE_CHECKING:
    from ..models.semanticalignment_negotiation_outcome import SemanticalignmentNegotiationOutcome
    from ..models.semanticalignment_round_offer import SemanticalignmentRoundOffer


T = TypeVar("T", bound="SemanticalignmentNegotiationTrace")


@_attrs_define
class SemanticalignmentNegotiationTrace:
    """
    Attributes:
        broken (bool | Unset): Broken indicates whether a participant explicitly broke off.
        final_agreement (list[SemanticalignmentNegotiationOutcome] | Unset): FinalAgreement is the agreed option per
            issue, if any.
        rounds (list[SemanticalignmentRoundOffer] | Unset): Rounds contains all SAO rounds in order (1-based).
        timedout (bool | Unset): Timedout indicates whether the SAO exhausted its step budget.
    """

    broken: bool | Unset = UNSET
    final_agreement: list[SemanticalignmentNegotiationOutcome] | Unset = UNSET
    rounds: list[SemanticalignmentRoundOffer] | Unset = UNSET
    timedout: bool | Unset = UNSET
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        broken = self.broken

        final_agreement: list[dict[str, Any]] | Unset = UNSET
        if not isinstance(self.final_agreement, Unset):
            final_agreement = []
            for final_agreement_item_data in self.final_agreement:
                final_agreement_item = final_agreement_item_data.to_dict()
                final_agreement.append(final_agreement_item)

        rounds: list[dict[str, Any]] | Unset = UNSET
        if not isinstance(self.rounds, Unset):
            rounds = []
            for rounds_item_data in self.rounds:
                rounds_item = rounds_item_data.to_dict()
                rounds.append(rounds_item)

        timedout = self.timedout

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update({})
        if broken is not UNSET:
            field_dict["broken"] = broken
        if final_agreement is not UNSET:
            field_dict["final_agreement"] = final_agreement
        if rounds is not UNSET:
            field_dict["rounds"] = rounds
        if timedout is not UNSET:
            field_dict["timedout"] = timedout

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.semanticalignment_negotiation_outcome import (
            SemanticalignmentNegotiationOutcome,
        )
        from ..models.semanticalignment_round_offer import SemanticalignmentRoundOffer

        d = dict(src_dict)
        broken = d.pop("broken", UNSET)

        _final_agreement = d.pop("final_agreement", UNSET)
        final_agreement: list[SemanticalignmentNegotiationOutcome] | Unset = UNSET
        if _final_agreement is not UNSET:
            final_agreement = []
            for final_agreement_item_data in _final_agreement:
                final_agreement_item = SemanticalignmentNegotiationOutcome.from_dict(
                    final_agreement_item_data
                )

                final_agreement.append(final_agreement_item)

        _rounds = d.pop("rounds", UNSET)
        rounds: list[SemanticalignmentRoundOffer] | Unset = UNSET
        if _rounds is not UNSET:
            rounds = []
            for rounds_item_data in _rounds:
                rounds_item = SemanticalignmentRoundOffer.from_dict(rounds_item_data)

                rounds.append(rounds_item)

        timedout = d.pop("timedout", UNSET)

        semanticalignment_negotiation_trace = cls(
            broken=broken,
            final_agreement=final_agreement,
            rounds=rounds,
            timedout=timedout,
        )

        semanticalignment_negotiation_trace.additional_properties = d
        return semanticalignment_negotiation_trace

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
