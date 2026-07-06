from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, TypeVar

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

if TYPE_CHECKING:
    from ..models.cognitionengine_masce_config_response_mas_config import (
        CognitionengineMASCEConfigResponseMasConfig,
    )


T = TypeVar("T", bound="CognitionengineMASCEConfigResponse")


@_attrs_define
class CognitionengineMASCEConfigResponse:
    """
    Attributes:
        ce_id (str | Unset):
        mas_config (CognitionengineMASCEConfigResponseMasConfig | Unset):
        mas_id (str | Unset):
        workspace_id (str | Unset):
    """

    ce_id: str | Unset = UNSET
    mas_config: CognitionengineMASCEConfigResponseMasConfig | Unset = UNSET
    mas_id: str | Unset = UNSET
    workspace_id: str | Unset = UNSET
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        ce_id = self.ce_id

        mas_config: dict[str, Any] | Unset = UNSET
        if not isinstance(self.mas_config, Unset):
            mas_config = self.mas_config.to_dict()

        mas_id = self.mas_id

        workspace_id = self.workspace_id

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update({})
        if ce_id is not UNSET:
            field_dict["ce_id"] = ce_id
        if mas_config is not UNSET:
            field_dict["mas_config"] = mas_config
        if mas_id is not UNSET:
            field_dict["mas_id"] = mas_id
        if workspace_id is not UNSET:
            field_dict["workspace_id"] = workspace_id

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.cognitionengine_masce_config_response_mas_config import (
            CognitionengineMASCEConfigResponseMasConfig,
        )

        d = dict(src_dict)
        ce_id = d.pop("ce_id", UNSET)

        _mas_config = d.pop("mas_config", UNSET)
        mas_config: CognitionengineMASCEConfigResponseMasConfig | Unset
        if isinstance(_mas_config, Unset):
            mas_config = UNSET
        else:
            mas_config = CognitionengineMASCEConfigResponseMasConfig.from_dict(_mas_config)

        mas_id = d.pop("mas_id", UNSET)

        workspace_id = d.pop("workspace_id", UNSET)

        cognitionengine_masce_config_response = cls(
            ce_id=ce_id,
            mas_config=mas_config,
            mas_id=mas_id,
            workspace_id=workspace_id,
        )

        cognitionengine_masce_config_response.additional_properties = d
        return cognitionengine_masce_config_response

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
