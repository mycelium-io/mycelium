from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, TypeVar, cast

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

if TYPE_CHECKING:
    from ..models.plan_file_out import PlanFileOut
    from ..models.task_out import TaskOut


T = TypeVar("T", bound="PlanOut")


@_attrs_define
class PlanOut:
    """
    Attributes:
        room (str):
        files (list[PlanFileOut]):
        tasks (list[TaskOut]):
        open_count (int):
        done_count (int):
        title (None | str | Unset):
    """

    room: str
    files: list[PlanFileOut]
    tasks: list[TaskOut]
    open_count: int
    done_count: int
    title: None | str | Unset = UNSET
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        room = self.room

        files = []
        for files_item_data in self.files:
            files_item = files_item_data.to_dict()
            files.append(files_item)

        tasks = []
        for tasks_item_data in self.tasks:
            tasks_item = tasks_item_data.to_dict()
            tasks.append(tasks_item)

        open_count = self.open_count

        done_count = self.done_count

        title: None | str | Unset
        if isinstance(self.title, Unset):
            title = UNSET
        else:
            title = self.title

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "room": room,
                "files": files,
                "tasks": tasks,
                "open_count": open_count,
                "done_count": done_count,
            }
        )
        if title is not UNSET:
            field_dict["title"] = title

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.plan_file_out import PlanFileOut
        from ..models.task_out import TaskOut

        d = dict(src_dict)
        room = d.pop("room")

        files = []
        _files = d.pop("files")
        for files_item_data in _files:
            files_item = PlanFileOut.from_dict(files_item_data)

            files.append(files_item)

        tasks = []
        _tasks = d.pop("tasks")
        for tasks_item_data in _tasks:
            tasks_item = TaskOut.from_dict(tasks_item_data)

            tasks.append(tasks_item)

        open_count = d.pop("open_count")

        done_count = d.pop("done_count")

        def _parse_title(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        title = _parse_title(d.pop("title", UNSET))

        plan_out = cls(
            room=room,
            files=files,
            tasks=tasks,
            open_count=open_count,
            done_count=done_count,
            title=title,
        )

        plan_out.additional_properties = d
        return plan_out

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
