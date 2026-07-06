from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, TypeVar, cast

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

if TYPE_CHECKING:
    from ..models.common_error_detail import CommonErrorDetail
    from ..models.common_header import CommonHeader


T = TypeVar("T", bound="CognitionagentsSharedMemoryVectorsResponse")


@_attrs_define
class CognitionagentsSharedMemoryVectorsResponse:
    """
    Attributes:
        error (CommonErrorDetail | Unset):
        header (CommonHeader | Unset):
        results (list[int] | Unset):
    """

    error: CommonErrorDetail | Unset = UNSET
    header: CommonHeader | Unset = UNSET
    results: list[int] | Unset = UNSET
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        error: dict[str, Any] | Unset = UNSET
        if not isinstance(self.error, Unset):
            error = self.error.to_dict()

        header: dict[str, Any] | Unset = UNSET
        if not isinstance(self.header, Unset):
            header = self.header.to_dict()

        results: list[int] | Unset = UNSET
        if not isinstance(self.results, Unset):
            results = self.results

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update({})
        if error is not UNSET:
            field_dict["error"] = error
        if header is not UNSET:
            field_dict["header"] = header
        if results is not UNSET:
            field_dict["results"] = results

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.common_error_detail import CommonErrorDetail
        from ..models.common_header import CommonHeader

        d = dict(src_dict)
        _error = d.pop("error", UNSET)
        error: CommonErrorDetail | Unset
        if isinstance(_error, Unset):
            error = UNSET
        else:
            error = CommonErrorDetail.from_dict(_error)

        _header = d.pop("header", UNSET)
        header: CommonHeader | Unset
        if isinstance(_header, Unset):
            header = UNSET
        else:
            header = CommonHeader.from_dict(_header)

        results = cast(list[int], d.pop("results", UNSET))

        cognitionagents_shared_memory_vectors_response = cls(
            error=error,
            header=header,
            results=results,
        )

        cognitionagents_shared_memory_vectors_response.additional_properties = d
        return cognitionagents_shared_memory_vectors_response

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
