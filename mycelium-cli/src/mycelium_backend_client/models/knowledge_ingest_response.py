from __future__ import annotations

import datetime
from collections.abc import Mapping
from typing import Any, TypeVar, cast

from attrs import define as _attrs_define
from attrs import field as _attrs_field
from dateutil.parser import isoparse

from ..types import UNSET, Unset

T = TypeVar("T", bound="KnowledgeIngestResponse")


@_attrs_define
class KnowledgeIngestResponse:
    """
    Attributes:
        cfn_response_id (str):
        ingested_at (datetime.datetime):
        estimated_cfn_knowledge_input_tokens (int):
        cfn_message (None | str | Unset):
    """

    cfn_response_id: str
    ingested_at: datetime.datetime
    estimated_cfn_knowledge_input_tokens: int
    cfn_message: None | str | Unset = UNSET
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        cfn_response_id = self.cfn_response_id

        ingested_at = self.ingested_at.isoformat()

        estimated_cfn_knowledge_input_tokens = self.estimated_cfn_knowledge_input_tokens

        cfn_message: None | str | Unset
        if isinstance(self.cfn_message, Unset):
            cfn_message = UNSET
        else:
            cfn_message = self.cfn_message

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "cfn_response_id": cfn_response_id,
                "ingested_at": ingested_at,
                "estimated_cfn_knowledge_input_tokens": estimated_cfn_knowledge_input_tokens,
            }
        )
        if cfn_message is not UNSET:
            field_dict["cfn_message"] = cfn_message

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        cfn_response_id = d.pop("cfn_response_id")

        ingested_at = isoparse(d.pop("ingested_at"))

        estimated_cfn_knowledge_input_tokens = d.pop("estimated_cfn_knowledge_input_tokens")

        def _parse_cfn_message(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        cfn_message = _parse_cfn_message(d.pop("cfn_message", UNSET))

        knowledge_ingest_response = cls(
            cfn_response_id=cfn_response_id,
            ingested_at=ingested_at,
            estimated_cfn_knowledge_input_tokens=estimated_cfn_knowledge_input_tokens,
            cfn_message=cfn_message,
        )

        knowledge_ingest_response.additional_properties = d
        return knowledge_ingest_response

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
