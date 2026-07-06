from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, TypeVar

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

if TYPE_CHECKING:
    from ..models.app_concept_similarity_search_header import AppConceptSimilaritySearchHeader
    from ..models.app_concept_similarity_search_payload import AppConceptSimilaritySearchPayload


T = TypeVar("T", bound="AppConceptSimilaritySearchRequest")


@_attrs_define
class AppConceptSimilaritySearchRequest:
    """
    Attributes:
        header (AppConceptSimilaritySearchHeader | Unset):
        payload (AppConceptSimilaritySearchPayload | Unset):
        request_id (str | Unset):
    """

    header: AppConceptSimilaritySearchHeader | Unset = UNSET
    payload: AppConceptSimilaritySearchPayload | Unset = UNSET
    request_id: str | Unset = UNSET
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        header: dict[str, Any] | Unset = UNSET
        if not isinstance(self.header, Unset):
            header = self.header.to_dict()

        payload: dict[str, Any] | Unset = UNSET
        if not isinstance(self.payload, Unset):
            payload = self.payload.to_dict()

        request_id = self.request_id

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update({})
        if header is not UNSET:
            field_dict["header"] = header
        if payload is not UNSET:
            field_dict["payload"] = payload
        if request_id is not UNSET:
            field_dict["request_id"] = request_id

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.app_concept_similarity_search_header import AppConceptSimilaritySearchHeader
        from ..models.app_concept_similarity_search_payload import AppConceptSimilaritySearchPayload

        d = dict(src_dict)
        _header = d.pop("header", UNSET)
        header: AppConceptSimilaritySearchHeader | Unset
        if isinstance(_header, Unset):
            header = UNSET
        else:
            header = AppConceptSimilaritySearchHeader.from_dict(_header)

        _payload = d.pop("payload", UNSET)
        payload: AppConceptSimilaritySearchPayload | Unset
        if isinstance(_payload, Unset):
            payload = UNSET
        else:
            payload = AppConceptSimilaritySearchPayload.from_dict(_payload)

        request_id = d.pop("request_id", UNSET)

        app_concept_similarity_search_request = cls(
            header=header,
            payload=payload,
            request_id=request_id,
        )

        app_concept_similarity_search_request.additional_properties = d
        return app_concept_similarity_search_request

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
