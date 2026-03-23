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
        key (str):
        value (MemoryCreateValueType0 | str): Memory content (dict or string)
        created_by (str): Agent handle creating this memory
        tags (list[str] | None | Unset):
        content_text (None | str | Unset): Text for embedding; auto-generated from value if omitted
        embed (bool | Unset): Generate vector embedding for semantic search Default: True.
        scope (str | Unset):  Default: 'namespace'.
        owner_handle (None | str | Unset): Required for notebook scope — the owning agent handle
    """

    key: str
    value: MemoryCreateValueType0 | str
    created_by: str
    tags: list[str] | None | Unset = UNSET
    content_text: None | str | Unset = UNSET
    embed: bool | Unset = True
    scope: str | Unset = "namespace"
    owner_handle: None | str | Unset = UNSET
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        from ..models.memory_create_value_type_0 import MemoryCreateValueType0

        key = self.key

        value: dict[str, Any] | str
        if isinstance(self.value, MemoryCreateValueType0):
            value = self.value.to_dict()
        else:
            value = self.value

        created_by = self.created_by

        tags: list[str] | None | Unset
        if isinstance(self.tags, Unset):
            tags = UNSET
        elif isinstance(self.tags, list):
            tags = self.tags

        else:
            tags = self.tags

        content_text: None | str | Unset
        if isinstance(self.content_text, Unset):
            content_text = UNSET
        else:
            content_text = self.content_text

        embed = self.embed

        scope = self.scope

        owner_handle: None | str | Unset
        if isinstance(self.owner_handle, Unset):
            owner_handle = UNSET
        else:
            owner_handle = self.owner_handle

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "key": key,
                "value": value,
                "created_by": created_by,
            }
        )
        if tags is not UNSET:
            field_dict["tags"] = tags
        if content_text is not UNSET:
            field_dict["content_text"] = content_text
        if embed is not UNSET:
            field_dict["embed"] = embed
        if scope is not UNSET:
            field_dict["scope"] = scope
        if owner_handle is not UNSET:
            field_dict["owner_handle"] = owner_handle

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.memory_create_value_type_0 import MemoryCreateValueType0

        d = dict(src_dict)
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

        created_by = d.pop("created_by")

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

        def _parse_content_text(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        content_text = _parse_content_text(d.pop("content_text", UNSET))

        embed = d.pop("embed", UNSET)

        scope = d.pop("scope", UNSET)

        def _parse_owner_handle(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        owner_handle = _parse_owner_handle(d.pop("owner_handle", UNSET))

        memory_create = cls(
            key=key,
            value=value,
            created_by=created_by,
            tags=tags,
            content_text=content_text,
            embed=embed,
            scope=scope,
            owner_handle=owner_handle,
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
