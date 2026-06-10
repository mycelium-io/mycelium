from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, TypeVar, cast

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

if TYPE_CHECKING:
    from ..models.query_request_additional_context_type_0 import QueryRequestAdditionalContextType0


T = TypeVar("T", bound="QueryRequest")


@_attrs_define
class QueryRequest:
    """
    Attributes:
        intent (str):
        additional_context (None | QueryRequestAdditionalContextType0 | Unset):
        agent_id (None | str | Unset):
        mas_id (None | str | Unset):
        search_strategy (str | Unset):  Default: 'semantic_graph_traversal'.
        workspace_id (None | str | Unset):
    """

    intent: str
    additional_context: None | QueryRequestAdditionalContextType0 | Unset = UNSET
    agent_id: None | str | Unset = UNSET
    mas_id: None | str | Unset = UNSET
    search_strategy: str | Unset = "semantic_graph_traversal"
    workspace_id: None | str | Unset = UNSET
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        from ..models.query_request_additional_context_type_0 import QueryRequestAdditionalContextType0

        intent = self.intent

        additional_context: dict[str, Any] | None | Unset
        if isinstance(self.additional_context, Unset):
            additional_context = UNSET
        elif isinstance(self.additional_context, QueryRequestAdditionalContextType0):
            additional_context = self.additional_context.to_dict()
        else:
            additional_context = self.additional_context

        agent_id: None | str | Unset
        if isinstance(self.agent_id, Unset):
            agent_id = UNSET
        else:
            agent_id = self.agent_id

        mas_id: None | str | Unset
        if isinstance(self.mas_id, Unset):
            mas_id = UNSET
        else:
            mas_id = self.mas_id

        search_strategy = self.search_strategy

        workspace_id: None | str | Unset
        if isinstance(self.workspace_id, Unset):
            workspace_id = UNSET
        else:
            workspace_id = self.workspace_id

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "intent": intent,
            }
        )
        if additional_context is not UNSET:
            field_dict["additional_context"] = additional_context
        if agent_id is not UNSET:
            field_dict["agent_id"] = agent_id
        if mas_id is not UNSET:
            field_dict["mas_id"] = mas_id
        if search_strategy is not UNSET:
            field_dict["search_strategy"] = search_strategy
        if workspace_id is not UNSET:
            field_dict["workspace_id"] = workspace_id

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.query_request_additional_context_type_0 import QueryRequestAdditionalContextType0

        d = dict(src_dict)
        intent = d.pop("intent")

        def _parse_additional_context(data: object) -> None | QueryRequestAdditionalContextType0 | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            try:
                if not isinstance(data, dict):
                    raise TypeError()
                additional_context_type_0 = QueryRequestAdditionalContextType0.from_dict(data)

                return additional_context_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(None | QueryRequestAdditionalContextType0 | Unset, data)

        additional_context = _parse_additional_context(d.pop("additional_context", UNSET))

        def _parse_agent_id(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        agent_id = _parse_agent_id(d.pop("agent_id", UNSET))

        def _parse_mas_id(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        mas_id = _parse_mas_id(d.pop("mas_id", UNSET))

        search_strategy = d.pop("search_strategy", UNSET)

        def _parse_workspace_id(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        workspace_id = _parse_workspace_id(d.pop("workspace_id", UNSET))

        query_request = cls(
            intent=intent,
            additional_context=additional_context,
            agent_id=agent_id,
            mas_id=mas_id,
            search_strategy=search_strategy,
            workspace_id=workspace_id,
        )

        query_request.additional_properties = d
        return query_request

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
