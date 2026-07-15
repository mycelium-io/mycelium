from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

T = TypeVar("T", bound="CommonTokenUsage")


@_attrs_define
class CommonTokenUsage:
    """
    Attributes:
        completion (int | Unset):
        model (str | Unset):
        prompt (int | Unset):
        total (int | Unset):
    """

    completion: int | Unset = UNSET
    model: str | Unset = UNSET
    prompt: int | Unset = UNSET
    total: int | Unset = UNSET
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        completion = self.completion

        model = self.model

        prompt = self.prompt

        total = self.total

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update({})
        if completion is not UNSET:
            field_dict["completion"] = completion
        if model is not UNSET:
            field_dict["model"] = model
        if prompt is not UNSET:
            field_dict["prompt"] = prompt
        if total is not UNSET:
            field_dict["total"] = total

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        completion = d.pop("completion", UNSET)

        model = d.pop("model", UNSET)

        prompt = d.pop("prompt", UNSET)

        total = d.pop("total", UNSET)

        common_token_usage = cls(
            completion=completion,
            model=model,
            prompt=prompt,
            total=total,
        )

        common_token_usage.additional_properties = d
        return common_token_usage

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
