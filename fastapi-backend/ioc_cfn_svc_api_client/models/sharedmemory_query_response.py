from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, TypeVar

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

if TYPE_CHECKING:
    from ..models.common_token_usage_meta import CommonTokenUsageMeta


T = TypeVar("T", bound="SharedmemoryQueryResponse")


@_attrs_define
class SharedmemoryQueryResponse:
    """
    Attributes:
        message (str | Unset): Message provides detailed information from the query result
        meta (CommonTokenUsageMeta | Unset):
        response_id (str | Unset): ID of the response, this gets populated from request_id
    """

    message: str | Unset = UNSET
    meta: CommonTokenUsageMeta | Unset = UNSET
    response_id: str | Unset = UNSET
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        message = self.message

        meta: dict[str, Any] | Unset = UNSET
        if not isinstance(self.meta, Unset):
            meta = self.meta.to_dict()

        response_id = self.response_id

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update({})
        if message is not UNSET:
            field_dict["message"] = message
        if meta is not UNSET:
            field_dict["meta"] = meta
        if response_id is not UNSET:
            field_dict["response_id"] = response_id

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.common_token_usage_meta import CommonTokenUsageMeta

        d = dict(src_dict)
        message = d.pop("message", UNSET)

        _meta = d.pop("meta", UNSET)
        meta: CommonTokenUsageMeta | Unset
        if isinstance(_meta, Unset):
            meta = UNSET
        else:
            meta = CommonTokenUsageMeta.from_dict(_meta)

        response_id = d.pop("response_id", UNSET)

        sharedmemory_query_response = cls(
            message=message,
            meta=meta,
            response_id=response_id,
        )

        sharedmemory_query_response.additional_properties = d
        return sharedmemory_query_response

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
