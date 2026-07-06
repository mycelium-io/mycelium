from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, TypeVar

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

if TYPE_CHECKING:
    from ..models.sharedmemory_header import SharedmemoryHeader
    from ..models.sharedmemory_query_request_additional_context_item import (
        SharedmemoryQueryRequestAdditionalContextItem,
    )


T = TypeVar("T", bound="SharedmemoryQueryRequest")


@_attrs_define
class SharedmemoryQueryRequest:
    """
    Attributes:
        additional_context (list[SharedmemoryQueryRequestAdditionalContextItem] | Unset): AdditionalContext provides
            optional contextual information to refine query execution. This may include prior conversation state, structured
            hints, or domain-specific metadata. The contents are treated as opaque by the API and interpreted by downstream
            components. Each element must be a structured object
        header (SharedmemoryHeader | Unset):
        intent (str | Unset): User intent or natural-language query describing what information is being requested. This
            field is required and is the primary signal used to construct and execute the query
        request_id (str | Unset): ID of the request, optional. If not provided, a random UUID is used to represent the
            request
        search_strategy (str | Unset): Search strategy to be used when executing the query. Currently supported values:
            "semantic_graph_traversal". If not specified, defaults to "semantic_graph_traversal"
    """

    additional_context: list[SharedmemoryQueryRequestAdditionalContextItem] | Unset = UNSET
    header: SharedmemoryHeader | Unset = UNSET
    intent: str | Unset = UNSET
    request_id: str | Unset = UNSET
    search_strategy: str | Unset = UNSET
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        additional_context: list[dict[str, Any]] | Unset = UNSET
        if not isinstance(self.additional_context, Unset):
            additional_context = []
            for additional_context_item_data in self.additional_context:
                additional_context_item = additional_context_item_data.to_dict()
                additional_context.append(additional_context_item)

        header: dict[str, Any] | Unset = UNSET
        if not isinstance(self.header, Unset):
            header = self.header.to_dict()

        intent = self.intent

        request_id = self.request_id

        search_strategy = self.search_strategy

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update({})
        if additional_context is not UNSET:
            field_dict["additional_context"] = additional_context
        if header is not UNSET:
            field_dict["header"] = header
        if intent is not UNSET:
            field_dict["intent"] = intent
        if request_id is not UNSET:
            field_dict["request_id"] = request_id
        if search_strategy is not UNSET:
            field_dict["search_strategy"] = search_strategy

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.sharedmemory_header import SharedmemoryHeader
        from ..models.sharedmemory_query_request_additional_context_item import (
            SharedmemoryQueryRequestAdditionalContextItem,
        )

        d = dict(src_dict)
        _additional_context = d.pop("additional_context", UNSET)
        additional_context: list[SharedmemoryQueryRequestAdditionalContextItem] | Unset = UNSET
        if _additional_context is not UNSET:
            additional_context = []
            for additional_context_item_data in _additional_context:
                additional_context_item = SharedmemoryQueryRequestAdditionalContextItem.from_dict(
                    additional_context_item_data
                )

                additional_context.append(additional_context_item)

        _header = d.pop("header", UNSET)
        header: SharedmemoryHeader | Unset
        if isinstance(_header, Unset):
            header = UNSET
        else:
            header = SharedmemoryHeader.from_dict(_header)

        intent = d.pop("intent", UNSET)

        request_id = d.pop("request_id", UNSET)

        search_strategy = d.pop("search_strategy", UNSET)

        sharedmemory_query_request = cls(
            additional_context=additional_context,
            header=header,
            intent=intent,
            request_id=request_id,
            search_strategy=search_strategy,
        )

        sharedmemory_query_request.additional_properties = d
        return sharedmemory_query_request

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
