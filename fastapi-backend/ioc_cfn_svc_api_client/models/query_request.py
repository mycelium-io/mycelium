from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, TypeVar, cast

from attrs import define as _attrs_define

from ..types import UNSET, Unset

if TYPE_CHECKING:
    from ..models.header import Header
    from ..models.query_request_additional_context_type_0 import QueryRequestAdditionalContextType0


T = TypeVar("T", bound="QueryRequest")


@_attrs_define
class QueryRequest:
    """
    Attributes:
        intent (str): The user’s query intent. This field is required and describes what the caller wants to search for
            or retrieve. Example: what does the website_selector_agent do?.
        header (Header | None | Unset): Optional header of the request.
        request_id (None | str | Unset): Client-supplied request identifier for tracing and idempotency. If omitted, the
            service generates a UUID. Example: 0f7c2b1e-8d0d-4d4d-9e2d-1a2b3c4d5e6f.
        search_strategy (None | str | Unset): Search strategy to use when processing the query. If omitted, defaults to
            `"semantic_graph_traversal"`. Default: 'semantic_graph_traversal'. Example: semantic_graph_traversal.
        additional_context (None | QueryRequestAdditionalContextType0 | Unset): Optional additional context used to
            influence query processing. May include arbitrary JSON key-value pairs such as filters, user context, or
            execution hints. Example: {'filters': {'environment': 'prod'}, 'session_id': 'abc-123'}.
    """

    intent: str
    header: Header | None | Unset = UNSET
    request_id: None | str | Unset = UNSET
    search_strategy: None | str | Unset = "semantic_graph_traversal"
    additional_context: None | QueryRequestAdditionalContextType0 | Unset = UNSET

    def to_dict(self) -> dict[str, Any]:
        from ..models.header import Header
        from ..models.query_request_additional_context_type_0 import (
            QueryRequestAdditionalContextType0,
        )

        intent = self.intent

        header: dict[str, Any] | None | Unset
        if isinstance(self.header, Unset):
            header = UNSET
        elif isinstance(self.header, Header):
            header = self.header.to_dict()
        else:
            header = self.header

        request_id: None | str | Unset
        if isinstance(self.request_id, Unset):
            request_id = UNSET
        else:
            request_id = self.request_id

        search_strategy: None | str | Unset
        if isinstance(self.search_strategy, Unset):
            search_strategy = UNSET
        else:
            search_strategy = self.search_strategy

        additional_context: dict[str, Any] | None | Unset
        if isinstance(self.additional_context, Unset):
            additional_context = UNSET
        elif isinstance(self.additional_context, QueryRequestAdditionalContextType0):
            additional_context = self.additional_context.to_dict()
        else:
            additional_context = self.additional_context

        field_dict: dict[str, Any] = {}

        field_dict.update(
            {
                "intent": intent,
            }
        )
        if header is not UNSET:
            field_dict["header"] = header
        if request_id is not UNSET:
            field_dict["request_id"] = request_id
        if search_strategy is not UNSET:
            field_dict["search_strategy"] = search_strategy
        if additional_context is not UNSET:
            field_dict["additional_context"] = additional_context

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.header import Header
        from ..models.query_request_additional_context_type_0 import (
            QueryRequestAdditionalContextType0,
        )

        d = dict(src_dict)
        intent = d.pop("intent")

        def _parse_header(data: object) -> Header | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            try:
                if not isinstance(data, dict):
                    raise TypeError()
                header_type_0 = Header.from_dict(data)

                return header_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(Header | None | Unset, data)

        header = _parse_header(d.pop("header", UNSET))

        def _parse_request_id(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        request_id = _parse_request_id(d.pop("request_id", UNSET))

        def _parse_search_strategy(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        search_strategy = _parse_search_strategy(d.pop("search_strategy", UNSET))

        def _parse_additional_context(
            data: object,
        ) -> None | QueryRequestAdditionalContextType0 | Unset:
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

        query_request = cls(
            intent=intent,
            header=header,
            request_id=request_id,
            search_strategy=search_strategy,
            additional_context=additional_context,
        )

        return query_request
