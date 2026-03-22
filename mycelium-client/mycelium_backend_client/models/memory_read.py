from __future__ import annotations

import datetime
from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, TypeVar, cast
from uuid import UUID

from attrs import define as _attrs_define
from attrs import field as _attrs_field
from dateutil.parser import isoparse

from ..types import UNSET, Unset

if TYPE_CHECKING:
    from ..models.memory_read_value_type_0 import MemoryReadValueType0


T = TypeVar("T", bound="MemoryRead")


@_attrs_define
class MemoryRead:
    """
    Attributes:
        id (UUID):
        room_name (str):
        key (str):
        value (MemoryReadValueType0 | str):
        created_by (str):
        version (int):
        created_at (datetime.datetime):
        updated_at (datetime.datetime):
        content_text (None | str | Unset):
        updated_by (None | str | Unset):
        tags (list[str] | None | Unset):
        scope (str | Unset):  Default: 'namespace'.
        owner_handle (None | str | Unset):
        file_path (None | str | Unset):
    """

    id: UUID
    room_name: str
    key: str
    value: MemoryReadValueType0 | str
    created_by: str
    version: int
    created_at: datetime.datetime
    updated_at: datetime.datetime
    content_text: None | str | Unset = UNSET
    updated_by: None | str | Unset = UNSET
    tags: list[str] | None | Unset = UNSET
    scope: str | Unset = "namespace"
    owner_handle: None | str | Unset = UNSET
    file_path: None | str | Unset = UNSET
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        from ..models.memory_read_value_type_0 import MemoryReadValueType0

        id = str(self.id)

        room_name = self.room_name

        key = self.key

        value: dict[str, Any] | str
        if isinstance(self.value, MemoryReadValueType0):
            value = self.value.to_dict()
        else:
            value = self.value

        created_by = self.created_by

        version = self.version

        created_at = self.created_at.isoformat()

        updated_at = self.updated_at.isoformat()

        content_text: None | str | Unset
        if isinstance(self.content_text, Unset):
            content_text = UNSET
        else:
            content_text = self.content_text

        updated_by: None | str | Unset
        if isinstance(self.updated_by, Unset):
            updated_by = UNSET
        else:
            updated_by = self.updated_by

        tags: list[str] | None | Unset
        if isinstance(self.tags, Unset):
            tags = UNSET
        elif isinstance(self.tags, list):
            tags = self.tags

        else:
            tags = self.tags

        scope = self.scope

        owner_handle: None | str | Unset
        if isinstance(self.owner_handle, Unset):
            owner_handle = UNSET
        else:
            owner_handle = self.owner_handle

        file_path: None | str | Unset
        if isinstance(self.file_path, Unset):
            file_path = UNSET
        else:
            file_path = self.file_path

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "id": id,
                "room_name": room_name,
                "key": key,
                "value": value,
                "created_by": created_by,
                "version": version,
                "created_at": created_at,
                "updated_at": updated_at,
            }
        )
        if content_text is not UNSET:
            field_dict["content_text"] = content_text
        if updated_by is not UNSET:
            field_dict["updated_by"] = updated_by
        if tags is not UNSET:
            field_dict["tags"] = tags
        if scope is not UNSET:
            field_dict["scope"] = scope
        if owner_handle is not UNSET:
            field_dict["owner_handle"] = owner_handle
        if file_path is not UNSET:
            field_dict["file_path"] = file_path

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.memory_read_value_type_0 import MemoryReadValueType0

        d = dict(src_dict)
        id = UUID(d.pop("id"))

        room_name = d.pop("room_name")

        key = d.pop("key")

        def _parse_value(data: object) -> MemoryReadValueType0 | str:
            try:
                if not isinstance(data, dict):
                    raise TypeError()
                value_type_0 = MemoryReadValueType0.from_dict(data)

                return value_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(MemoryReadValueType0 | str, data)

        value = _parse_value(d.pop("value"))

        created_by = d.pop("created_by")

        version = d.pop("version")

        created_at = isoparse(d.pop("created_at"))

        updated_at = isoparse(d.pop("updated_at"))

        def _parse_content_text(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        content_text = _parse_content_text(d.pop("content_text", UNSET))

        def _parse_updated_by(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        updated_by = _parse_updated_by(d.pop("updated_by", UNSET))

        def _parse_tags(data: object) -> list[str] | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            try:
                if not isinstance(data, list):
                    raise TypeError()
                tags_type_0 = cast(list[str], data)

                return tags_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(list[str] | None | Unset, data)

        tags = _parse_tags(d.pop("tags", UNSET))

        scope = d.pop("scope", UNSET)

        def _parse_owner_handle(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        owner_handle = _parse_owner_handle(d.pop("owner_handle", UNSET))

        def _parse_file_path(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        file_path = _parse_file_path(d.pop("file_path", UNSET))

        memory_read = cls(
            id=id,
            room_name=room_name,
            key=key,
            value=value,
            created_by=created_by,
            version=version,
            created_at=created_at,
            updated_at=updated_at,
            content_text=content_text,
            updated_by=updated_by,
            tags=tags,
            scope=scope,
            owner_handle=owner_handle,
            file_path=file_path,
        )

        memory_read.additional_properties = d
        return memory_read

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
