from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, TypeVar, cast

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

if TYPE_CHECKING:
    from ..models.cognitionengine_register_request_auth import CognitionengineRegisterRequestAuth
    from ..models.cognitionengine_register_request_config import (
        CognitionengineRegisterRequestConfig,
    )
    from ..models.cognitionengine_register_request_mas_config import (
        CognitionengineRegisterRequestMasConfig,
    )


T = TypeVar("T", bound="CognitionengineRegisterRequest")


@_attrs_define
class CognitionengineRegisterRequest:
    """
    Attributes:
        auth (CognitionengineRegisterRequestAuth | Unset):
        capabilities (list[str] | Unset):
        config (CognitionengineRegisterRequestConfig | Unset):
        kind (str | Unset): CE kind (e.g., "knowledge", "contingency")
        mas_auto_associate (bool | Unset): No omitempty - always send (defaults to false)
        mas_config (CognitionengineRegisterRequestMasConfig | Unset):
        metrics (list[str] | Unset):
        name (str | Unset):
        subkind (str | Unset): CE subkind (e.g., "distillation", "query", "negotiation")
        url (str | Unset):
        version (str | Unset):
    """

    auth: CognitionengineRegisterRequestAuth | Unset = UNSET
    capabilities: list[str] | Unset = UNSET
    config: CognitionengineRegisterRequestConfig | Unset = UNSET
    kind: str | Unset = UNSET
    mas_auto_associate: bool | Unset = UNSET
    mas_config: CognitionengineRegisterRequestMasConfig | Unset = UNSET
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

        config: dict[str, Any] | Unset = UNSET
        if not isinstance(self.config, Unset):
            config = self.config.to_dict()

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
        if config is not UNSET:
            field_dict["config"] = config
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
        from ..models.cognitionengine_register_request_auth import (
            CognitionengineRegisterRequestAuth,
        )
        from ..models.cognitionengine_register_request_config import (
            CognitionengineRegisterRequestConfig,
        )
        from ..models.cognitionengine_register_request_mas_config import (
            CognitionengineRegisterRequestMasConfig,
        )

        d = dict(src_dict)
        _auth = d.pop("auth", UNSET)
        auth: CognitionengineRegisterRequestAuth | Unset
        if isinstance(_auth, Unset):
            auth = UNSET
        else:
            auth = CognitionengineRegisterRequestAuth.from_dict(_auth)

        capabilities = cast(list[str], d.pop("capabilities", UNSET))

        _config = d.pop("config", UNSET)
        config: CognitionengineRegisterRequestConfig | Unset
        if isinstance(_config, Unset):
            config = UNSET
        else:
            config = CognitionengineRegisterRequestConfig.from_dict(_config)

        kind = d.pop("kind", UNSET)

        mas_auto_associate = d.pop("mas_auto_associate", UNSET)

        _mas_config = d.pop("mas_config", UNSET)
        mas_config: CognitionengineRegisterRequestMasConfig | Unset
        if isinstance(_mas_config, Unset):
            mas_config = UNSET
        else:
            mas_config = CognitionengineRegisterRequestMasConfig.from_dict(_mas_config)

        metrics = cast(list[str], d.pop("metrics", UNSET))

        name = d.pop("name", UNSET)

        subkind = d.pop("subkind", UNSET)

        url = d.pop("url", UNSET)

        version = d.pop("version", UNSET)

        cognitionengine_register_request = cls(
            auth=auth,
            capabilities=capabilities,
            config=config,
            kind=kind,
            mas_auto_associate=mas_auto_associate,
            mas_config=mas_config,
            metrics=metrics,
            name=name,
            subkind=subkind,
            url=url,
            version=version,
        )

        cognitionengine_register_request.additional_properties = d
        return cognitionengine_register_request

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
