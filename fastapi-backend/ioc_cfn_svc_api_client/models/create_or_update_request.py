from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, TypeVar, cast

from attrs import define as _attrs_define

from ..types import UNSET, Unset

if TYPE_CHECKING:
    from ..models.extraction_payload import ExtractionPayload
    from ..models.header import Header


T = TypeVar("T", bound="CreateOrUpdateRequest")


@_attrs_define
class CreateOrUpdateRequest:
    """
    Attributes:
        payload (ExtractionPayload):
        header (Header | None | Unset): Optional header of the request.
        request_id (None | str | Unset): Client-supplied request identifier for tracing and idempotency. If omitted, the
            service generates a UUID. Example: 0f7c2b1e-8d0d-4d4d-9e2d-1a2b3c4d5e6f.
    """

    payload: ExtractionPayload
    header: Header | None | Unset = UNSET
    request_id: None | str | Unset = UNSET

    def to_dict(self) -> dict[str, Any]:
        from ..models.header import Header

        payload = self.payload.to_dict()

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

        field_dict: dict[str, Any] = {}

        field_dict.update(
            {
                "payload": payload,
            }
        )
        if header is not UNSET:
            field_dict["header"] = header
        if request_id is not UNSET:
            field_dict["request_id"] = request_id

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.extraction_payload import ExtractionPayload
        from ..models.header import Header

        d = dict(src_dict)
        payload = ExtractionPayload.from_dict(d.pop("payload"))

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

        create_or_update_request = cls(
            payload=payload,
            header=header,
            request_id=request_id,
        )

        return create_or_update_request
