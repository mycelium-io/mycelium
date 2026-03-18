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
    from ..models.mas_read_config_type_0 import MASReadConfigType0


T = TypeVar("T", bound="MASRead")


@_attrs_define
class MASRead:
    """
    Attributes:
        id (UUID):
        workspace_id (UUID):
        name (str):
        created_at (datetime.datetime):
        config (MASReadConfigType0 | None | Unset):
    """

    id: UUID
    workspace_id: UUID
    name: str
    created_at: datetime.datetime
    config: MASReadConfigType0 | None | Unset = UNSET
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        from ..models.mas_read_config_type_0 import MASReadConfigType0

        id = str(self.id)

        workspace_id = str(self.workspace_id)

        name = self.name

        created_at = self.created_at.isoformat()

        config: dict[str, Any] | None | Unset
        if isinstance(self.config, Unset):
            config = UNSET
        elif isinstance(self.config, MASReadConfigType0):
            config = self.config.to_dict()
        else:
            config = self.config

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "id": id,
                "workspace_id": workspace_id,
                "name": name,
                "created_at": created_at,
            }
        )
        if config is not UNSET:
            field_dict["config"] = config

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.mas_read_config_type_0 import MASReadConfigType0

        d = dict(src_dict)
        id = UUID(d.pop("id"))

        workspace_id = UUID(d.pop("workspace_id"))

        name = d.pop("name")

        created_at = isoparse(d.pop("created_at"))

        def _parse_config(data: object) -> MASReadConfigType0 | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            try:
                if not isinstance(data, dict):
                    raise TypeError()
                config_type_0 = MASReadConfigType0.from_dict(data)

                return config_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(MASReadConfigType0 | None | Unset, data)

        config = _parse_config(d.pop("config", UNSET))

        mas_read = cls(
            id=id,
            workspace_id=workspace_id,
            name=name,
            created_at=created_at,
            config=config,
        )

        mas_read.additional_properties = d
        return mas_read

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
