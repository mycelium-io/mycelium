from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, cast

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..models.event_provenance_ref_type import EventProvenanceRefType
from ..types import UNSET, Unset

T = TypeVar("T", bound="EventProvenanceRef")


@_attrs_define
class EventProvenanceRef:
    """A cited reference backing an event.

    Attributes:
        type_ (EventProvenanceRefType):
        ref (str): e.g. 'org/repo#48' or a message id
        url (None | str | Unset):
    """

    type_: EventProvenanceRefType
    ref: str
    url: None | str | Unset = UNSET
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        type_ = self.type_.value

        ref = self.ref

        url: None | str | Unset
        if isinstance(self.url, Unset):
            url = UNSET
        else:
            url = self.url

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "type": type_,
                "ref": ref,
            }
        )
        if url is not UNSET:
            field_dict["url"] = url

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        type_ = EventProvenanceRefType(d.pop("type"))

        ref = d.pop("ref")

        def _parse_url(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        url = _parse_url(d.pop("url", UNSET))

        event_provenance_ref = cls(
            type_=type_,
            ref=ref,
            url=url,
        )

        event_provenance_ref.additional_properties = d
        return event_provenance_ref

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
