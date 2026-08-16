from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, TypeVar

from attrs import define as _attrs_define
from attrs import field as _attrs_field

if TYPE_CHECKING:
    from ..models.episode_summary_read import EpisodeSummaryRead


T = TypeVar("T", bound="EpisodeListResponse")


@_attrs_define
class EpisodeListResponse:
    """
    Attributes:
        episodes (list[EpisodeSummaryRead]):
    """

    episodes: list[EpisodeSummaryRead]
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        episodes = []
        for episodes_item_data in self.episodes:
            episodes_item = episodes_item_data.to_dict()
            episodes.append(episodes_item)

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "episodes": episodes,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.episode_summary_read import EpisodeSummaryRead

        d = dict(src_dict)
        episodes = []
        _episodes = d.pop("episodes")
        for episodes_item_data in _episodes:
            episodes_item = EpisodeSummaryRead.from_dict(episodes_item_data)

            episodes.append(episodes_item)

        episode_list_response = cls(
            episodes=episodes,
        )

        episode_list_response.additional_properties = d
        return episode_list_response

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
