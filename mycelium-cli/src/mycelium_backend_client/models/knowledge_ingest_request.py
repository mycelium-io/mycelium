from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, TypeVar, cast

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

if TYPE_CHECKING:
    from ..models.knowledge_ingest_request_records_item import KnowledgeIngestRequestRecordsItem


T = TypeVar("T", bound="KnowledgeIngestRequest")


@_attrs_define
class KnowledgeIngestRequest:
    """
    Attributes:
        records (list[KnowledgeIngestRequestRecordsItem]):
        agent_id (None | str | Unset):
        room_name (None | str | Unset):
        workspace_id (None | str | Unset):
        mas_id (None | str | Unset):
    """

    records: list[KnowledgeIngestRequestRecordsItem]
    agent_id: None | str | Unset = UNSET
    room_name: None | str | Unset = UNSET
    workspace_id: None | str | Unset = UNSET
    mas_id: None | str | Unset = UNSET
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        records = []
        for records_item_data in self.records:
            records_item = records_item_data.to_dict()
            records.append(records_item)

        agent_id: None | str | Unset
        if isinstance(self.agent_id, Unset):
            agent_id = UNSET
        else:
            agent_id = self.agent_id

        room_name: None | str | Unset
        if isinstance(self.room_name, Unset):
            room_name = UNSET
        else:
            room_name = self.room_name

        workspace_id: None | str | Unset
        if isinstance(self.workspace_id, Unset):
            workspace_id = UNSET
        else:
            workspace_id = self.workspace_id

        mas_id: None | str | Unset
        if isinstance(self.mas_id, Unset):
            mas_id = UNSET
        else:
            mas_id = self.mas_id

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "records": records,
            }
        )
        if agent_id is not UNSET:
            field_dict["agent_id"] = agent_id
        if room_name is not UNSET:
            field_dict["room_name"] = room_name
        if workspace_id is not UNSET:
            field_dict["workspace_id"] = workspace_id
        if mas_id is not UNSET:
            field_dict["mas_id"] = mas_id

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.knowledge_ingest_request_records_item import KnowledgeIngestRequestRecordsItem

        d = dict(src_dict)
        records = []
        _records = d.pop("records")
        for records_item_data in _records:
            records_item = KnowledgeIngestRequestRecordsItem.from_dict(records_item_data)

            records.append(records_item)

        def _parse_agent_id(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        agent_id = _parse_agent_id(d.pop("agent_id", UNSET))

        def _parse_room_name(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        room_name = _parse_room_name(d.pop("room_name", UNSET))

        def _parse_workspace_id(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        workspace_id = _parse_workspace_id(d.pop("workspace_id", UNSET))

        def _parse_mas_id(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        mas_id = _parse_mas_id(d.pop("mas_id", UNSET))

        knowledge_ingest_request = cls(
            records=records,
            agent_id=agent_id,
            room_name=room_name,
            workspace_id=workspace_id,
            mas_id=mas_id,
        )

        knowledge_ingest_request.additional_properties = d
        return knowledge_ingest_request

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
