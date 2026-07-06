from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

T = TypeVar("T", bound="AppConceptSimilaritySearchResponseHeader")


@_attrs_define
class AppConceptSimilaritySearchResponseHeader:
    """
    Attributes:
        agent_id (str | Unset):
        mas_id (str | Unset):
        workspace_id (str | Unset):
    """

    agent_id: str | Unset = UNSET
    mas_id: str | Unset = UNSET
    workspace_id: str | Unset = UNSET
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        agent_id = self.agent_id

        mas_id = self.mas_id

        workspace_id = self.workspace_id

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update({})
        if agent_id is not UNSET:
            field_dict["agent_id"] = agent_id
        if mas_id is not UNSET:
            field_dict["mas_id"] = mas_id
        if workspace_id is not UNSET:
            field_dict["workspace_id"] = workspace_id

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        agent_id = d.pop("agent_id", UNSET)

        mas_id = d.pop("mas_id", UNSET)

        workspace_id = d.pop("workspace_id", UNSET)

        app_concept_similarity_search_response_header = cls(
            agent_id=agent_id,
            mas_id=mas_id,
            workspace_id=workspace_id,
        )

        app_concept_similarity_search_response_header.additional_properties = d
        return app_concept_similarity_search_response_header

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
