from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, TypeVar, cast

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..models.knowledge_graph_store_request_memory_type_type_0 import (
    KnowledgeGraphStoreRequestMemoryTypeType0,
)
from ..types import UNSET, Unset

if TYPE_CHECKING:
    from ..models.knowledge_graph_store_request_records_type_0 import (
        KnowledgeGraphStoreRequestRecordsType0,
    )


T = TypeVar("T", bound="KnowledgeGraphStoreRequest")


@_attrs_define
class KnowledgeGraphStoreRequest:
    """
    Attributes:
        request_id (str | Unset):
        records (KnowledgeGraphStoreRequestRecordsType0 | None | Unset):
        memory_type (KnowledgeGraphStoreRequestMemoryTypeType0 | None | Unset):
        mas_id (None | str | Unset):
        wksp_id (None | str | Unset):
        force_replace (bool | Unset):  Default: False.
    """

    request_id: str | Unset = UNSET
    records: KnowledgeGraphStoreRequestRecordsType0 | None | Unset = UNSET
    memory_type: KnowledgeGraphStoreRequestMemoryTypeType0 | None | Unset = UNSET
    mas_id: None | str | Unset = UNSET
    wksp_id: None | str | Unset = UNSET
    force_replace: bool | Unset = False
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        from ..models.knowledge_graph_store_request_records_type_0 import (
            KnowledgeGraphStoreRequestRecordsType0,
        )

        request_id = self.request_id

        records: dict[str, Any] | None | Unset
        if isinstance(self.records, Unset):
            records = UNSET
        elif isinstance(self.records, KnowledgeGraphStoreRequestRecordsType0):
            records = self.records.to_dict()
        else:
            records = self.records

        memory_type: None | str | Unset
        if isinstance(self.memory_type, Unset):
            memory_type = UNSET
        elif isinstance(self.memory_type, KnowledgeGraphStoreRequestMemoryTypeType0):
            memory_type = self.memory_type.value
        else:
            memory_type = self.memory_type

        mas_id: None | str | Unset
        if isinstance(self.mas_id, Unset):
            mas_id = UNSET
        else:
            mas_id = self.mas_id

        wksp_id: None | str | Unset
        if isinstance(self.wksp_id, Unset):
            wksp_id = UNSET
        else:
            wksp_id = self.wksp_id

        force_replace = self.force_replace

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update({})
        if request_id is not UNSET:
            field_dict["request_id"] = request_id
        if records is not UNSET:
            field_dict["records"] = records
        if memory_type is not UNSET:
            field_dict["memory_type"] = memory_type
        if mas_id is not UNSET:
            field_dict["mas_id"] = mas_id
        if wksp_id is not UNSET:
            field_dict["wksp_id"] = wksp_id
        if force_replace is not UNSET:
            field_dict["force_replace"] = force_replace

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.knowledge_graph_store_request_records_type_0 import (
            KnowledgeGraphStoreRequestRecordsType0,
        )

        d = dict(src_dict)
        request_id = d.pop("request_id", UNSET)

        def _parse_records(data: object) -> KnowledgeGraphStoreRequestRecordsType0 | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            try:
                if not isinstance(data, dict):
                    raise TypeError()
                records_type_0 = KnowledgeGraphStoreRequestRecordsType0.from_dict(data)

                return records_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(KnowledgeGraphStoreRequestRecordsType0 | None | Unset, data)

        records = _parse_records(d.pop("records", UNSET))

        def _parse_memory_type(
            data: object,
        ) -> KnowledgeGraphStoreRequestMemoryTypeType0 | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            try:
                if not isinstance(data, str):
                    raise TypeError()
                memory_type_type_0 = KnowledgeGraphStoreRequestMemoryTypeType0(data)

                return memory_type_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(KnowledgeGraphStoreRequestMemoryTypeType0 | None | Unset, data)

        memory_type = _parse_memory_type(d.pop("memory_type", UNSET))

        def _parse_mas_id(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        mas_id = _parse_mas_id(d.pop("mas_id", UNSET))

        def _parse_wksp_id(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        wksp_id = _parse_wksp_id(d.pop("wksp_id", UNSET))

        force_replace = d.pop("force_replace", UNSET)

        knowledge_graph_store_request = cls(
            request_id=request_id,
            records=records,
            memory_type=memory_type,
            mas_id=mas_id,
            wksp_id=wksp_id,
            force_replace=force_replace,
        )

        knowledge_graph_store_request.additional_properties = d
        return knowledge_graph_store_request

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
