from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, TypeVar, cast

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

if TYPE_CHECKING:
    from ..models.knowledge_graph_query_criteria import KnowledgeGraphQueryCriteria
    from ..models.knowledge_graph_query_request_records import KnowledgeGraphQueryRequestRecords


T = TypeVar("T", bound="KnowledgeGraphQueryRequest")


@_attrs_define
class KnowledgeGraphQueryRequest:
    """
    Attributes:
        records (KnowledgeGraphQueryRequestRecords):
        request_id (str | Unset):
        memory_type (None | str | Unset):
        mas_id (None | str | Unset):
        wksp_id (None | str | Unset):
        query_criteria (KnowledgeGraphQueryCriteria | None | Unset):
    """

    records: KnowledgeGraphQueryRequestRecords
    request_id: str | Unset = UNSET
    memory_type: None | str | Unset = UNSET
    mas_id: None | str | Unset = UNSET
    wksp_id: None | str | Unset = UNSET
    query_criteria: KnowledgeGraphQueryCriteria | None | Unset = UNSET
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        from ..models.knowledge_graph_query_criteria import KnowledgeGraphQueryCriteria

        records = self.records.to_dict()

        request_id = self.request_id

        memory_type: None | str | Unset
        if isinstance(self.memory_type, Unset):
            memory_type = UNSET
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

        query_criteria: dict[str, Any] | None | Unset
        if isinstance(self.query_criteria, Unset):
            query_criteria = UNSET
        elif isinstance(self.query_criteria, KnowledgeGraphQueryCriteria):
            query_criteria = self.query_criteria.to_dict()
        else:
            query_criteria = self.query_criteria

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "records": records,
            }
        )
        if request_id is not UNSET:
            field_dict["request_id"] = request_id
        if memory_type is not UNSET:
            field_dict["memory_type"] = memory_type
        if mas_id is not UNSET:
            field_dict["mas_id"] = mas_id
        if wksp_id is not UNSET:
            field_dict["wksp_id"] = wksp_id
        if query_criteria is not UNSET:
            field_dict["query_criteria"] = query_criteria

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.knowledge_graph_query_criteria import KnowledgeGraphQueryCriteria
        from ..models.knowledge_graph_query_request_records import KnowledgeGraphQueryRequestRecords

        d = dict(src_dict)
        records = KnowledgeGraphQueryRequestRecords.from_dict(d.pop("records"))

        request_id = d.pop("request_id", UNSET)

        def _parse_memory_type(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

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

        def _parse_query_criteria(data: object) -> KnowledgeGraphQueryCriteria | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            try:
                if not isinstance(data, dict):
                    raise TypeError()
                query_criteria_type_0 = KnowledgeGraphQueryCriteria.from_dict(data)

                return query_criteria_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(KnowledgeGraphQueryCriteria | None | Unset, data)

        query_criteria = _parse_query_criteria(d.pop("query_criteria", UNSET))

        knowledge_graph_query_request = cls(
            records=records,
            request_id=request_id,
            memory_type=memory_type,
            mas_id=mas_id,
            wksp_id=wksp_id,
            query_criteria=query_criteria,
        )

        knowledge_graph_query_request.additional_properties = d
        return knowledge_graph_query_request

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
