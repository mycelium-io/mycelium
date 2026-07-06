from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, TypeVar

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

if TYPE_CHECKING:
    from ..models.common_error_detail_detail import CommonErrorDetailDetail


T = TypeVar("T", bound="CommonErrorDetail")


@_attrs_define
class CommonErrorDetail:
    """
    Attributes:
        detail (CommonErrorDetailDetail | Unset):
        message (str | Unset):
    """

    detail: CommonErrorDetailDetail | Unset = UNSET
    message: str | Unset = UNSET
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        detail: dict[str, Any] | Unset = UNSET
        if not isinstance(self.detail, Unset):
            detail = self.detail.to_dict()

        message = self.message

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update({})
        if detail is not UNSET:
            field_dict["detail"] = detail
        if message is not UNSET:
            field_dict["message"] = message

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.common_error_detail_detail import CommonErrorDetailDetail

        d = dict(src_dict)
        _detail = d.pop("detail", UNSET)
        detail: CommonErrorDetailDetail | Unset
        if isinstance(_detail, Unset):
            detail = UNSET
        else:
            detail = CommonErrorDetailDetail.from_dict(_detail)

        message = d.pop("message", UNSET)

        common_error_detail = cls(
            detail=detail,
            message=message,
        )

        common_error_detail.additional_properties = d
        return common_error_detail

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
