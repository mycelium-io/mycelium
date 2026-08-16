from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, cast

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

T = TypeVar("T", bound="EpisodeMetricsRead")


@_attrs_define
class EpisodeMetricsRead:
    """
    Attributes:
        mpc (float | Unset):  Default: 0.0.
        gar (float | Unset):  Default: 0.0.
        scr (float | Unset):  Default: 0.0.
        provenance_weight (float | Unset):  Default: 0.0.
        participants (int | None | Unset):
    """

    mpc: float | Unset = 0.0
    gar: float | Unset = 0.0
    scr: float | Unset = 0.0
    provenance_weight: float | Unset = 0.0
    participants: int | None | Unset = UNSET
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        mpc = self.mpc

        gar = self.gar

        scr = self.scr

        provenance_weight = self.provenance_weight

        participants: int | None | Unset
        if isinstance(self.participants, Unset):
            participants = UNSET
        else:
            participants = self.participants

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update({})
        if mpc is not UNSET:
            field_dict["mpc"] = mpc
        if gar is not UNSET:
            field_dict["gar"] = gar
        if scr is not UNSET:
            field_dict["scr"] = scr
        if provenance_weight is not UNSET:
            field_dict["provenance_weight"] = provenance_weight
        if participants is not UNSET:
            field_dict["participants"] = participants

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        mpc = d.pop("mpc", UNSET)

        gar = d.pop("gar", UNSET)

        scr = d.pop("scr", UNSET)

        provenance_weight = d.pop("provenance_weight", UNSET)

        def _parse_participants(data: object) -> int | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(int | None | Unset, data)

        participants = _parse_participants(d.pop("participants", UNSET))

        episode_metrics_read = cls(
            mpc=mpc,
            gar=gar,
            scr=scr,
            provenance_weight=provenance_weight,
            participants=participants,
        )

        episode_metrics_read.additional_properties = d
        return episode_metrics_read

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
