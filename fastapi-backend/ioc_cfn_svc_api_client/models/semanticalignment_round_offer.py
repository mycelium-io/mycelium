from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, TypeVar

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

if TYPE_CHECKING:
    from ..models.semanticalignment_agent_decision import SemanticalignmentAgentDecision
    from ..models.semanticalignment_round_offer_offer import SemanticalignmentRoundOfferOffer


T = TypeVar("T", bound="SemanticalignmentRoundOffer")


@_attrs_define
class SemanticalignmentRoundOffer:
    """
    Attributes:
        decisions (list[SemanticalignmentAgentDecision] | Unset): Decisions contains each participant's response to this
            round's offer.
        next_proposer_id (str | Unset): NextProposerID is the ID of the participant who will propose in the next round.
            Omitted on the final round.
        offer (SemanticalignmentRoundOfferOffer | Unset): Offer is the proposed option per issue. Shape: {issue_id:
            option_label}
        proposer_id (str | Unset): ProposerID is the ID of the participant who made this proposal.
        round_ (int | Unset): Round is the 1-based round number.
    """

    decisions: list[SemanticalignmentAgentDecision] | Unset = UNSET
    next_proposer_id: str | Unset = UNSET
    offer: SemanticalignmentRoundOfferOffer | Unset = UNSET
    proposer_id: str | Unset = UNSET
    round_: int | Unset = UNSET
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        decisions: list[dict[str, Any]] | Unset = UNSET
        if not isinstance(self.decisions, Unset):
            decisions = []
            for decisions_item_data in self.decisions:
                decisions_item = decisions_item_data.to_dict()
                decisions.append(decisions_item)

        next_proposer_id = self.next_proposer_id

        offer: dict[str, Any] | Unset = UNSET
        if not isinstance(self.offer, Unset):
            offer = self.offer.to_dict()

        proposer_id = self.proposer_id

        round_ = self.round_

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update({})
        if decisions is not UNSET:
            field_dict["decisions"] = decisions
        if next_proposer_id is not UNSET:
            field_dict["next_proposer_id"] = next_proposer_id
        if offer is not UNSET:
            field_dict["offer"] = offer
        if proposer_id is not UNSET:
            field_dict["proposer_id"] = proposer_id
        if round_ is not UNSET:
            field_dict["round"] = round_

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.semanticalignment_agent_decision import SemanticalignmentAgentDecision
        from ..models.semanticalignment_round_offer_offer import SemanticalignmentRoundOfferOffer

        d = dict(src_dict)
        _decisions = d.pop("decisions", UNSET)
        decisions: list[SemanticalignmentAgentDecision] | Unset = UNSET
        if _decisions is not UNSET:
            decisions = []
            for decisions_item_data in _decisions:
                decisions_item = SemanticalignmentAgentDecision.from_dict(decisions_item_data)

                decisions.append(decisions_item)

        next_proposer_id = d.pop("next_proposer_id", UNSET)

        _offer = d.pop("offer", UNSET)
        offer: SemanticalignmentRoundOfferOffer | Unset
        if isinstance(_offer, Unset):
            offer = UNSET
        else:
            offer = SemanticalignmentRoundOfferOffer.from_dict(_offer)

        proposer_id = d.pop("proposer_id", UNSET)

        round_ = d.pop("round", UNSET)

        semanticalignment_round_offer = cls(
            decisions=decisions,
            next_proposer_id=next_proposer_id,
            offer=offer,
            proposer_id=proposer_id,
            round_=round_,
        )

        semanticalignment_round_offer.additional_properties = d
        return semanticalignment_round_offer

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
