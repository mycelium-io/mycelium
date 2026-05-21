from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, TypeVar, cast

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

if TYPE_CHECKING:
    from ..models.memory_create_value_type_0 import MemoryCreateValueType0


T = TypeVar("T", bound="MemoryCreate")


@_attrs_define
class MemoryCreate:
    """
    Attributes:
        created_by (str): Agent handle creating this memory
        key (str):
        value (MemoryCreateValueType0 | str): Memory content (dict or string)
        content_text (None | str | Unset): Text for embedding; auto-generated from value if omitted
        embed (bool | Unset): Generate vector embedding for semantic search Default: True.
        tags (list[str] | None | Unset):
    """

    created_by: str
    key: str
    value: MemoryCreateValueType0 | str
    content_text: None | str | Unset = UNSET
    embed: bool | Unset = True
    tags: list[str] | None | Unset = UNSET
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        from ..models.memory_create_value_type_0 import MemoryCreateValueType0

        created_by = self.created_by

        key = self.key

        value: dict[str, Any] | str
        if isinstance(self.value, MemoryCreateValueType0):
            value = self.value.to_dict()
        else:
            value = self.value

        content_text: None | str | Unset
        if isinstance(self.content_text, Unset):
            content_text = UNSET
        else:
            content_text = self.content_text

        embed = self.embed

        tags: list[str] | None | Unset
        if isinstance(self.tags, Unset):
            tags = UNSET
        elif isinstance(self.tags, list):
            tags = self.tags

        else:
            tags = self.tags

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "created_by": created_by,
                "key": key,
                "value": value,
            }
        )
        if content_text is not UNSET:
            field_dict["content_text"] = content_text
        if embed is not UNSET:
            field_dict["embed"] = embed
        if tags is not UNSET:
            field_dict["tags"] = tags

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.memory_create_value_type_0 import MemoryCreateValueType0

        d = dict(src_dict)
        created_by = d.pop("created_by")

        key = d.pop("key")

        def _parse_value(data: object) -> MemoryCreateValueType0 | str:
            try:
                if not isinstance(data, dict):
                    raise TypeError()
                value_type_0 = MemoryCreateValueType0.from_dict(data)

                return value_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(MemoryCreateValueType0 | str, data)

        value = _parse_value(d.pop("value"))

        def _parse_content_text(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        content_text = _parse_content_text(d.pop("content_text", UNSET))

        embed = d.pop("embed", UNSET)

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

        memory_create = cls(
            created_by=created_by,
            key=key,
            value=value,
            content_text=content_text,
            embed=embed,
            tags=tags,
        )

        memory_create.additional_properties = d
        return memory_create

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
