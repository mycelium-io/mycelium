from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, TypeVar, cast
from uuid import UUID

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

if TYPE_CHECKING:
    from ..models.audit_event_create_audit_information_type_0 import AuditEventCreateAuditInformationType0


T = TypeVar("T", bound="AuditEventCreate")


@_attrs_define
class AuditEventCreate:
    """
    Attributes:
        resource_type (str):
        resource_identifier (str):
        audit_type (str):
        audit_resource_identifier (str):
        created_by (UUID):
        last_modified_by (UUID):
        operation_id (None | str | Unset):
        audit_information (AuditEventCreateAuditInformationType0 | None | Unset):
        audit_extra_information (None | str | Unset):
    """

    resource_type: str
    resource_identifier: str
    audit_type: str
    audit_resource_identifier: str
    created_by: UUID
    last_modified_by: UUID
    operation_id: None | str | Unset = UNSET
    audit_information: AuditEventCreateAuditInformationType0 | None | Unset = UNSET
    audit_extra_information: None | str | Unset = UNSET
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        from ..models.audit_event_create_audit_information_type_0 import AuditEventCreateAuditInformationType0

        resource_type = self.resource_type

        resource_identifier = self.resource_identifier

        audit_type = self.audit_type

        audit_resource_identifier = self.audit_resource_identifier

        created_by = str(self.created_by)

        last_modified_by = str(self.last_modified_by)

        operation_id: None | str | Unset
        if isinstance(self.operation_id, Unset):
            operation_id = UNSET
        else:
            operation_id = self.operation_id

        audit_information: dict[str, Any] | None | Unset
        if isinstance(self.audit_information, Unset):
            audit_information = UNSET
        elif isinstance(self.audit_information, AuditEventCreateAuditInformationType0):
            audit_information = self.audit_information.to_dict()
        else:
            audit_information = self.audit_information

        audit_extra_information: None | str | Unset
        if isinstance(self.audit_extra_information, Unset):
            audit_extra_information = UNSET
        else:
            audit_extra_information = self.audit_extra_information

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "resource_type": resource_type,
                "resource_identifier": resource_identifier,
                "audit_type": audit_type,
                "audit_resource_identifier": audit_resource_identifier,
                "created_by": created_by,
                "last_modified_by": last_modified_by,
            }
        )
        if operation_id is not UNSET:
            field_dict["operation_id"] = operation_id
        if audit_information is not UNSET:
            field_dict["audit_information"] = audit_information
        if audit_extra_information is not UNSET:
            field_dict["audit_extra_information"] = audit_extra_information

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.audit_event_create_audit_information_type_0 import AuditEventCreateAuditInformationType0

        d = dict(src_dict)
        resource_type = d.pop("resource_type")

        resource_identifier = d.pop("resource_identifier")

        audit_type = d.pop("audit_type")

        audit_resource_identifier = d.pop("audit_resource_identifier")

        created_by = UUID(d.pop("created_by"))

        last_modified_by = UUID(d.pop("last_modified_by"))

        def _parse_operation_id(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        operation_id = _parse_operation_id(d.pop("operation_id", UNSET))

        def _parse_audit_information(data: object) -> AuditEventCreateAuditInformationType0 | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            try:
                if not isinstance(data, dict):
                    raise TypeError()
                audit_information_type_0 = AuditEventCreateAuditInformationType0.from_dict(data)

                return audit_information_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(AuditEventCreateAuditInformationType0 | None | Unset, data)

        audit_information = _parse_audit_information(d.pop("audit_information", UNSET))

        def _parse_audit_extra_information(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        audit_extra_information = _parse_audit_extra_information(d.pop("audit_extra_information", UNSET))

        audit_event_create = cls(
            resource_type=resource_type,
            resource_identifier=resource_identifier,
            audit_type=audit_type,
            audit_resource_identifier=audit_resource_identifier,
            created_by=created_by,
            last_modified_by=last_modified_by,
            operation_id=operation_id,
            audit_information=audit_information,
            audit_extra_information=audit_extra_information,
        )

        audit_event_create.additional_properties = d
        return audit_event_create

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
