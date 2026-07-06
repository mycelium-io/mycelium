from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, TypeVar, cast

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

if TYPE_CHECKING:
    from ..models.cognitionengine_patch_request_auth import CognitionenginePatchRequestAuth
    from ..models.cognitionengine_patch_request_config import CognitionenginePatchRequestConfig
    from ..models.cognitionengine_patch_request_mas_config import (
        CognitionenginePatchRequestMasConfig,
    )


T = TypeVar("T", bound="CognitionenginePatchRequest")


@_attrs_define
class CognitionenginePatchRequest:
    """
    Attributes:
        auth (CognitionenginePatchRequestAuth | Unset):
        capabilities (list[str] | Unset):
        cfn_id (str | Unset): Immutable fields - included to trigger validation error if provided
        config (CognitionenginePatchRequestConfig | Unset):
        enabled (bool | Unset):
        kind (str | Unset):
        mas_auto_associate (bool | Unset):
        mas_config (CognitionenginePatchRequestMasConfig | Unset):
        metrics (list[str] | Unset):
        name (str | Unset):
        subkind (str | Unset):
        url (str | Unset): Mutable fields
        version (str | Unset):
    """

    auth: CognitionenginePatchRequestAuth | Unset = UNSET
    capabilities: list[str] | Unset = UNSET
    cfn_id: str | Unset = UNSET
    config: CognitionenginePatchRequestConfig | Unset = UNSET
    enabled: bool | Unset = UNSET
    kind: str | Unset = UNSET
    mas_auto_associate: bool | Unset = UNSET
    mas_config: CognitionenginePatchRequestMasConfig | Unset = UNSET
    metrics: list[str] | Unset = UNSET
    name: str | Unset = UNSET
    subkind: str | Unset = UNSET
    url: str | Unset = UNSET
    version: str | Unset = UNSET
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        auth: dict[str, Any] | Unset = UNSET
        if not isinstance(self.auth, Unset):
            auth = self.auth.to_dict()

        capabilities: list[str] | Unset = UNSET
        if not isinstance(self.capabilities, Unset):
            capabilities = self.capabilities

        cfn_id = self.cfn_id

        config: dict[str, Any] | Unset = UNSET
        if not isinstance(self.config, Unset):
            config = self.config.to_dict()

        enabled = self.enabled

        kind = self.kind

        mas_auto_associate = self.mas_auto_associate

        mas_config: dict[str, Any] | Unset = UNSET
        if not isinstance(self.mas_config, Unset):
            mas_config = self.mas_config.to_dict()

        metrics: list[str] | Unset = UNSET
        if not isinstance(self.metrics, Unset):
            metrics = self.metrics

        name = self.name

        subkind = self.subkind

        url = self.url

        version = self.version

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update({})
        if auth is not UNSET:
            field_dict["auth"] = auth
        if capabilities is not UNSET:
            field_dict["capabilities"] = capabilities
        if cfn_id is not UNSET:
            field_dict["cfn_id"] = cfn_id
        if config is not UNSET:
            field_dict["config"] = config
        if enabled is not UNSET:
            field_dict["enabled"] = enabled
        if kind is not UNSET:
            field_dict["kind"] = kind
        if mas_auto_associate is not UNSET:
            field_dict["mas_auto_associate"] = mas_auto_associate
        if mas_config is not UNSET:
            field_dict["mas_config"] = mas_config
        if metrics is not UNSET:
            field_dict["metrics"] = metrics
        if name is not UNSET:
            field_dict["name"] = name
        if subkind is not UNSET:
            field_dict["subkind"] = subkind
        if url is not UNSET:
            field_dict["url"] = url
        if version is not UNSET:
            field_dict["version"] = version

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.cognitionengine_patch_request_auth import CognitionenginePatchRequestAuth
        from ..models.cognitionengine_patch_request_config import CognitionenginePatchRequestConfig
        from ..models.cognitionengine_patch_request_mas_config import (
            CognitionenginePatchRequestMasConfig,
        )

        d = dict(src_dict)
        _auth = d.pop("auth", UNSET)
        auth: CognitionenginePatchRequestAuth | Unset
        if isinstance(_auth, Unset):
            auth = UNSET
        else:
            auth = CognitionenginePatchRequestAuth.from_dict(_auth)

        capabilities = cast(list[str], d.pop("capabilities", UNSET))

        cfn_id = d.pop("cfn_id", UNSET)

        _config = d.pop("config", UNSET)
        config: CognitionenginePatchRequestConfig | Unset
        if isinstance(_config, Unset):
            config = UNSET
        else:
            config = CognitionenginePatchRequestConfig.from_dict(_config)

        enabled = d.pop("enabled", UNSET)

        kind = d.pop("kind", UNSET)

        mas_auto_associate = d.pop("mas_auto_associate", UNSET)

        _mas_config = d.pop("mas_config", UNSET)
        mas_config: CognitionenginePatchRequestMasConfig | Unset
        if isinstance(_mas_config, Unset):
            mas_config = UNSET
        else:
            mas_config = CognitionenginePatchRequestMasConfig.from_dict(_mas_config)

        metrics = cast(list[str], d.pop("metrics", UNSET))

        name = d.pop("name", UNSET)

        subkind = d.pop("subkind", UNSET)

        url = d.pop("url", UNSET)

        version = d.pop("version", UNSET)

        cognitionengine_patch_request = cls(
            auth=auth,
            capabilities=capabilities,
            cfn_id=cfn_id,
            config=config,
            enabled=enabled,
            kind=kind,
            mas_auto_associate=mas_auto_associate,
            mas_config=mas_config,
            metrics=metrics,
            name=name,
            subkind=subkind,
            url=url,
            version=version,
        )

        cognitionengine_patch_request.additional_properties = d
        return cognitionengine_patch_request

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
