from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, TypeVar

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

if TYPE_CHECKING:
    from ..models.common_token_usage import CommonTokenUsage


T = TypeVar("T", bound="CommonTokenUsageMeta")


@_attrs_define
class CommonTokenUsageMeta:
    """
    Attributes:
        ce_id (str | Unset): CE that performed the operation (for metrics attribution)
        cost_usd (float | Unset):
        latency_ms (float | Unset):
        timestamp (str | Unset):
        tokens (CommonTokenUsage | Unset):
    """

    ce_id: str | Unset = UNSET
    cost_usd: float | Unset = UNSET
    latency_ms: float | Unset = UNSET
    timestamp: str | Unset = UNSET
    tokens: CommonTokenUsage | Unset = UNSET
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        ce_id = self.ce_id

        cost_usd = self.cost_usd

        latency_ms = self.latency_ms

        timestamp = self.timestamp

        tokens: dict[str, Any] | Unset = UNSET
        if not isinstance(self.tokens, Unset):
            tokens = self.tokens.to_dict()

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update({})
        if ce_id is not UNSET:
            field_dict["ce_id"] = ce_id
        if cost_usd is not UNSET:
            field_dict["cost_usd"] = cost_usd
        if latency_ms is not UNSET:
            field_dict["latency_ms"] = latency_ms
        if timestamp is not UNSET:
            field_dict["timestamp"] = timestamp
        if tokens is not UNSET:
            field_dict["tokens"] = tokens

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.common_token_usage import CommonTokenUsage

        d = dict(src_dict)
        ce_id = d.pop("ce_id", UNSET)

        cost_usd = d.pop("cost_usd", UNSET)

        latency_ms = d.pop("latency_ms", UNSET)

        timestamp = d.pop("timestamp", UNSET)

        _tokens = d.pop("tokens", UNSET)
        tokens: CommonTokenUsage | Unset
        if isinstance(_tokens, Unset):
            tokens = UNSET
        else:
            tokens = CommonTokenUsage.from_dict(_tokens)

        common_token_usage_meta = cls(
            ce_id=ce_id,
            cost_usd=cost_usd,
            latency_ms=latency_ms,
            timestamp=timestamp,
            tokens=tokens,
        )

        common_token_usage_meta.additional_properties = d
        return common_token_usage_meta

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
