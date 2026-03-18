from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, TypeVar, cast

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

if TYPE_CHECKING:
    from ..models.agent_create_memory_config_type_0 import AgentCreateMemoryConfigType0


T = TypeVar("T", bound="AgentCreate")


@_attrs_define
class AgentCreate:
    """
    Attributes:
        name (str):
        memory_provider_url (None | str | Unset):
        memory_config (AgentCreateMemoryConfigType0 | None | Unset):
    """

    name: str
    memory_provider_url: None | str | Unset = UNSET
    memory_config: AgentCreateMemoryConfigType0 | None | Unset = UNSET
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        from ..models.agent_create_memory_config_type_0 import AgentCreateMemoryConfigType0

        name = self.name

        memory_provider_url: None | str | Unset
        if isinstance(self.memory_provider_url, Unset):
            memory_provider_url = UNSET
        else:
            memory_provider_url = self.memory_provider_url

        memory_config: dict[str, Any] | None | Unset
        if isinstance(self.memory_config, Unset):
            memory_config = UNSET
        elif isinstance(self.memory_config, AgentCreateMemoryConfigType0):
            memory_config = self.memory_config.to_dict()
        else:
            memory_config = self.memory_config

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "name": name,
            }
        )
        if memory_provider_url is not UNSET:
            field_dict["memory_provider_url"] = memory_provider_url
        if memory_config is not UNSET:
            field_dict["memory_config"] = memory_config

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.agent_create_memory_config_type_0 import AgentCreateMemoryConfigType0

        d = dict(src_dict)
        name = d.pop("name")

        def _parse_memory_provider_url(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        memory_provider_url = _parse_memory_provider_url(d.pop("memory_provider_url", UNSET))

        def _parse_memory_config(data: object) -> AgentCreateMemoryConfigType0 | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            try:
                if not isinstance(data, dict):
                    raise TypeError()
                memory_config_type_0 = AgentCreateMemoryConfigType0.from_dict(data)

                return memory_config_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(AgentCreateMemoryConfigType0 | None | Unset, data)

        memory_config = _parse_memory_config(d.pop("memory_config", UNSET))

        agent_create = cls(
            name=name,
            memory_provider_url=memory_provider_url,
            memory_config=memory_config,
        )

        agent_create.additional_properties = d
        return agent_create

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
