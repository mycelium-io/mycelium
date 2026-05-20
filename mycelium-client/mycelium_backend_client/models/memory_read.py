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
        created_at (datetime.datetime):
        created_by (str):
        id (UUID):
        key (str):
        room_name (str):
        updated_at (datetime.datetime):
        value (MemoryReadValueType0 | str):
        version (int):
        content_text (None | str | Unset):
        file_path (None | str | Unset):
        tags (list[str] | None | Unset):
        updated_by (None | str | Unset):
    """

    created_at: datetime.datetime
    created_by: str
    id: UUID
    key: str
    room_name: str
    updated_at: datetime.datetime
    value: MemoryReadValueType0 | str
    version: int
    content_text: None | str | Unset = UNSET
    file_path: None | str | Unset = UNSET
    tags: list[str] | None | Unset = UNSET
    updated_by: None | str | Unset = UNSET
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        from ..models.memory_read_value_type_0 import MemoryReadValueType0

        created_at = self.created_at.isoformat()

        created_by = self.created_by

        id = str(self.id)

        key = self.key

        room_name = self.room_name

        updated_at = self.updated_at.isoformat()

        value: dict[str, Any] | str
        if isinstance(self.value, MemoryReadValueType0):
            value = self.value.to_dict()
        else:
            value = self.value

        version = self.version

        content_text: None | str | Unset
        if isinstance(self.content_text, Unset):
            content_text = UNSET
        else:
            content_text = self.content_text

        file_path: None | str | Unset
        if isinstance(self.file_path, Unset):
            file_path = UNSET
        else:
            file_path = self.file_path

        tags: list[str] | None | Unset
        if isinstance(self.tags, Unset):
            tags = UNSET
        elif isinstance(self.tags, list):
            tags = self.tags

        else:
            tags = self.tags

        updated_by: None | str | Unset
        if isinstance(self.updated_by, Unset):
            updated_by = UNSET
        else:
            updated_by = self.updated_by

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "created_at": created_at,
                "created_by": created_by,
                "id": id,
                "key": key,
                "room_name": room_name,
                "updated_at": updated_at,
                "value": value,
                "version": version,
            }
        )
        if content_text is not UNSET:
            field_dict["content_text"] = content_text
        if file_path is not UNSET:
            field_dict["file_path"] = file_path
        if tags is not UNSET:
            field_dict["tags"] = tags
        if updated_by is not UNSET:
            field_dict["updated_by"] = updated_by

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.memory_read_value_type_0 import MemoryReadValueType0

        d = dict(src_dict)
        created_at = isoparse(d.pop("created_at"))

        created_by = d.pop("created_by")

        id = UUID(d.pop("id"))

        key = d.pop("key")

        room_name = d.pop("room_name")

        updated_at = isoparse(d.pop("updated_at"))

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

        version = d.pop("version")

        def _parse_content_text(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        content_text = _parse_content_text(d.pop("content_text", UNSET))

        def _parse_file_path(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        file_path = _parse_file_path(d.pop("file_path", UNSET))

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

        def _parse_updated_by(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        updated_by = _parse_updated_by(d.pop("updated_by", UNSET))

        memory_read = cls(
            created_at=created_at,
            created_by=created_by,
            id=id,
            key=key,
            room_name=room_name,
            updated_at=updated_at,
            value=value,
            version=version,
            content_text=content_text,
            file_path=file_path,
            tags=tags,
            updated_by=updated_by,
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
