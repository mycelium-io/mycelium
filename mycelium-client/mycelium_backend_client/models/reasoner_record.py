from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, TypeVar

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

if TYPE_CHECKING:
    from ..models.reasoner_record_content import ReasonerRecordContent


T = TypeVar("T", bound="ReasonerRecord")


@_attrs_define
class ReasonerRecord:
    """
    Attributes:
        content (ReasonerRecordContent | Unset):
    """

    content: ReasonerRecordContent | Unset = UNSET
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        content: dict[str, Any] | Unset = UNSET
        if not isinstance(self.content, Unset):
            content = self.content.to_dict()

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update({})
        if content is not UNSET:
            field_dict["content"] = content

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.reasoner_record_content import ReasonerRecordContent

        d = dict(src_dict)
        _content = d.pop("content", UNSET)
        content: ReasonerRecordContent | Unset
        if isinstance(_content, Unset):
            content = UNSET
        else:
            content = ReasonerRecordContent.from_dict(_content)

        reasoner_record = cls(
            content=content,
        )

        reasoner_record.additional_properties = d
        return reasoner_record

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
