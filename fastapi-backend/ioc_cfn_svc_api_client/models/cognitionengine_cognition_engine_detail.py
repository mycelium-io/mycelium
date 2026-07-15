from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, TypeVar, cast

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

if TYPE_CHECKING:
    from ..models.cognitionengine_cognition_engine_detail_config import (
        CognitionengineCognitionEngineDetailConfig,
    )
    from ..models.cognitionengine_cognition_engine_detail_mas_config import (
        CognitionengineCognitionEngineDetailMasConfig,
    )


T = TypeVar("T", bound="CognitionengineCognitionEngineDetail")


@_attrs_define
class CognitionengineCognitionEngineDetail:
    """
    Attributes:
        capabilities (list[str] | Unset):
        cfn_id (str | Unset):
        config (CognitionengineCognitionEngineDetailConfig | Unset):
        created_at (str | Unset):
        enabled (bool | Unset):
        id (str | Unset):
        kind (str | Unset):
        last_seen (str | Unset):
        mas_auto_associate (bool | Unset):
        mas_config (CognitionengineCognitionEngineDetailMasConfig | Unset):
        metrics (list[str] | Unset):
        name (str | Unset):
        status (str | Unset):
        subkind (str | Unset):
        updated_at (str | Unset):
        url (str | Unset):
        version (str | Unset):
    """

    capabilities: list[str] | Unset = UNSET
    cfn_id: str | Unset = UNSET
    config: CognitionengineCognitionEngineDetailConfig | Unset = UNSET
    created_at: str | Unset = UNSET
    enabled: bool | Unset = UNSET
    id: str | Unset = UNSET
    kind: str | Unset = UNSET
    last_seen: str | Unset = UNSET
    mas_auto_associate: bool | Unset = UNSET
    mas_config: CognitionengineCognitionEngineDetailMasConfig | Unset = UNSET
    metrics: list[str] | Unset = UNSET
    name: str | Unset = UNSET
    status: str | Unset = UNSET
    subkind: str | Unset = UNSET
    updated_at: str | Unset = UNSET
    url: str | Unset = UNSET
    version: str | Unset = UNSET
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        capabilities: list[str] | Unset = UNSET
        if not isinstance(self.capabilities, Unset):
            capabilities = self.capabilities

        cfn_id = self.cfn_id

        config: dict[str, Any] | Unset = UNSET
        if not isinstance(self.config, Unset):
            config = self.config.to_dict()

        created_at = self.created_at

        enabled = self.enabled

        id = self.id

        kind = self.kind

        last_seen = self.last_seen

        mas_auto_associate = self.mas_auto_associate

        mas_config: dict[str, Any] | Unset = UNSET
        if not isinstance(self.mas_config, Unset):
            mas_config = self.mas_config.to_dict()

        metrics: list[str] | Unset = UNSET
        if not isinstance(self.metrics, Unset):
            metrics = self.metrics

        name = self.name

        status = self.status

        subkind = self.subkind

        updated_at = self.updated_at

        url = self.url

        version = self.version

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update({})
        if capabilities is not UNSET:
            field_dict["capabilities"] = capabilities
        if cfn_id is not UNSET:
            field_dict["cfn_id"] = cfn_id
        if config is not UNSET:
            field_dict["config"] = config
        if created_at is not UNSET:
            field_dict["created_at"] = created_at
        if enabled is not UNSET:
            field_dict["enabled"] = enabled
        if id is not UNSET:
            field_dict["id"] = id
        if kind is not UNSET:
            field_dict["kind"] = kind
        if last_seen is not UNSET:
            field_dict["last_seen"] = last_seen
        if mas_auto_associate is not UNSET:
            field_dict["mas_auto_associate"] = mas_auto_associate
        if mas_config is not UNSET:
            field_dict["mas_config"] = mas_config
        if metrics is not UNSET:
            field_dict["metrics"] = metrics
        if name is not UNSET:
            field_dict["name"] = name
        if status is not UNSET:
            field_dict["status"] = status
        if subkind is not UNSET:
            field_dict["subkind"] = subkind
        if updated_at is not UNSET:
            field_dict["updated_at"] = updated_at
        if url is not UNSET:
            field_dict["url"] = url
        if version is not UNSET:
            field_dict["version"] = version

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.cognitionengine_cognition_engine_detail_config import (
            CognitionengineCognitionEngineDetailConfig,
        )
        from ..models.cognitionengine_cognition_engine_detail_mas_config import (
            CognitionengineCognitionEngineDetailMasConfig,
        )

        d = dict(src_dict)
        capabilities = cast(list[str], d.pop("capabilities", UNSET))

        cfn_id = d.pop("cfn_id", UNSET)

        _config = d.pop("config", UNSET)
        config: CognitionengineCognitionEngineDetailConfig | Unset
        if isinstance(_config, Unset):
            config = UNSET
        else:
            config = CognitionengineCognitionEngineDetailConfig.from_dict(_config)

        created_at = d.pop("created_at", UNSET)

        enabled = d.pop("enabled", UNSET)

        id = d.pop("id", UNSET)

        kind = d.pop("kind", UNSET)

        last_seen = d.pop("last_seen", UNSET)

        mas_auto_associate = d.pop("mas_auto_associate", UNSET)

        _mas_config = d.pop("mas_config", UNSET)
        mas_config: CognitionengineCognitionEngineDetailMasConfig | Unset
        if isinstance(_mas_config, Unset):
            mas_config = UNSET
        else:
            mas_config = CognitionengineCognitionEngineDetailMasConfig.from_dict(_mas_config)

        metrics = cast(list[str], d.pop("metrics", UNSET))

        name = d.pop("name", UNSET)

        status = d.pop("status", UNSET)

        subkind = d.pop("subkind", UNSET)

        updated_at = d.pop("updated_at", UNSET)

        url = d.pop("url", UNSET)

        version = d.pop("version", UNSET)

        cognitionengine_cognition_engine_detail = cls(
            capabilities=capabilities,
            cfn_id=cfn_id,
            config=config,
            created_at=created_at,
            enabled=enabled,
            id=id,
            kind=kind,
            last_seen=last_seen,
            mas_auto_associate=mas_auto_associate,
            mas_config=mas_config,
            metrics=metrics,
            name=name,
            status=status,
            subkind=subkind,
            updated_at=updated_at,
            url=url,
            version=version,
        )

        cognitionengine_cognition_engine_detail.additional_properties = d
        return cognitionengine_cognition_engine_detail

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
