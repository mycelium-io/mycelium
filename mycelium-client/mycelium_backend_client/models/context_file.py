from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar

from attrs import define as _attrs_define
from attrs import field as _attrs_field

T = TypeVar("T", bound="ContextFile")


@_attrs_define
class ContextFile:
    """An opt-in shared file injected into a coordination session.

    The agent (via the CLI) explicitly selected this file to share with the
    session. Content is visible to other participants on tick fan-out and
    counts as a deliberate room write — it flows to KXP/CFN like any other
    room artifact. Use ``sha256`` for audit/dedupe and ``path`` for display.

        Attributes:
            path (str): Absolute or repo-relative path on the sender's machine
            content (str): File contents at join time
            sha256 (str): hex sha256 of content for audit and dedupe
    """

    path: str
    content: str
    sha256: str
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        path = self.path

        content = self.content

        sha256 = self.sha256

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "path": path,
                "content": content,
                "sha256": sha256,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        path = d.pop("path")

        content = d.pop("content")

        sha256 = d.pop("sha256")

        context_file = cls(
            path=path,
            content=content,
            sha256=sha256,
        )

        context_file.additional_properties = d
        return context_file

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
