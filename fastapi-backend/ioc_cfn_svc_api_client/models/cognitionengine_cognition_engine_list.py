from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, TypeVar

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

if TYPE_CHECKING:
    from ..models.cognitionengine_cognition_engine_list_item import (
        CognitionengineCognitionEngineListItem,
    )


T = TypeVar("T", bound="CognitionengineCognitionEngineList")


@_attrs_define
class CognitionengineCognitionEngineList:
    """
    Attributes:
        cognition_engines (list[CognitionengineCognitionEngineListItem] | Unset):
        total (int | Unset):
    """

    cognition_engines: list[CognitionengineCognitionEngineListItem] | Unset = UNSET
    total: int | Unset = UNSET
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        cognition_engines: list[dict[str, Any]] | Unset = UNSET
        if not isinstance(self.cognition_engines, Unset):
            cognition_engines = []
            for cognition_engines_item_data in self.cognition_engines:
                cognition_engines_item = cognition_engines_item_data.to_dict()
                cognition_engines.append(cognition_engines_item)

        total = self.total

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update({})
        if cognition_engines is not UNSET:
            field_dict["cognition_engines"] = cognition_engines
        if total is not UNSET:
            field_dict["total"] = total

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.cognitionengine_cognition_engine_list_item import (
            CognitionengineCognitionEngineListItem,
        )

        d = dict(src_dict)
        _cognition_engines = d.pop("cognition_engines", UNSET)
        cognition_engines: list[CognitionengineCognitionEngineListItem] | Unset = UNSET
        if _cognition_engines is not UNSET:
            cognition_engines = []
            for cognition_engines_item_data in _cognition_engines:
                cognition_engines_item = CognitionengineCognitionEngineListItem.from_dict(
                    cognition_engines_item_data
                )

                cognition_engines.append(cognition_engines_item)

        total = d.pop("total", UNSET)

        cognitionengine_cognition_engine_list = cls(
            cognition_engines=cognition_engines,
            total=total,
        )

        cognitionengine_cognition_engine_list.additional_properties = d
        return cognitionengine_cognition_engine_list

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
