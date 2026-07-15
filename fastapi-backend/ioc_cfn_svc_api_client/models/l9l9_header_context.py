from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, TypeVar

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

if TYPE_CHECKING:
    from ..models.l9l9_header_context_epistemic import L9L9HeaderContextEpistemic
    from ..models.l9l9_header_context_semantic import L9L9HeaderContextSemantic


T = TypeVar("T", bound="L9L9HeaderContext")


@_attrs_define
class L9L9HeaderContext:
    """
    Attributes:
        epistemic (L9L9HeaderContextEpistemic | Unset):
        semantic (L9L9HeaderContextSemantic | Unset):
        topic (str | Unset): Topic corresponds to the JSON schema field "topic".
    """

    epistemic: L9L9HeaderContextEpistemic | Unset = UNSET
    semantic: L9L9HeaderContextSemantic | Unset = UNSET
    topic: str | Unset = UNSET
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        epistemic: dict[str, Any] | Unset = UNSET
        if not isinstance(self.epistemic, Unset):
            epistemic = self.epistemic.to_dict()

        semantic: dict[str, Any] | Unset = UNSET
        if not isinstance(self.semantic, Unset):
            semantic = self.semantic.to_dict()

        topic = self.topic

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update({})
        if epistemic is not UNSET:
            field_dict["epistemic"] = epistemic
        if semantic is not UNSET:
            field_dict["semantic"] = semantic
        if topic is not UNSET:
            field_dict["topic"] = topic

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.l9l9_header_context_epistemic import L9L9HeaderContextEpistemic
        from ..models.l9l9_header_context_semantic import L9L9HeaderContextSemantic

        d = dict(src_dict)
        _epistemic = d.pop("epistemic", UNSET)
        epistemic: L9L9HeaderContextEpistemic | Unset
        if isinstance(_epistemic, Unset):
            epistemic = UNSET
        else:
            epistemic = L9L9HeaderContextEpistemic.from_dict(_epistemic)

        _semantic = d.pop("semantic", UNSET)
        semantic: L9L9HeaderContextSemantic | Unset
        if isinstance(_semantic, Unset):
            semantic = UNSET
        else:
            semantic = L9L9HeaderContextSemantic.from_dict(_semantic)

        topic = d.pop("topic", UNSET)

        l9l9_header_context = cls(
            epistemic=epistemic,
            semantic=semantic,
            topic=topic,
        )

        l9l9_header_context.additional_properties = d
        return l9l9_header_context

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
