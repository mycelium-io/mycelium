# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""A room's skills on the hub: memories under ``skills/``, read and written by name.

``mycelium skill ...`` sends these. A refusal raises
:class:`~mycelium.exceptions.HubError`. (The skill this package ships for
agents to read is the file ``skills/mycelium/SKILL.md`` beside this module.)
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from mycelium.exceptions import HubError

if TYPE_CHECKING:
    from mycelium_backend_client import Client
    from mycelium_backend_client.models import SkillListResponse, SkillRead


def save_skill(
    client: Client,
    room: str,
    *,
    name: str,
    body: str,
    description: str,
    created_by: str,
    tags: list[str] | None = None,
) -> SkillRead:
    """Create or update a skill (an upsert: an existing one gets a new version)."""
    from mycelium.client import answered
    from mycelium_backend_client.api.skills import (
        create_skill_api_rooms_room_name_skills_post as create_api,
    )
    from mycelium_backend_client.models import SkillCreate, SkillRead

    item = SkillCreate(
        name=name, body=body, description=description, created_by=created_by, tags=tags
    )
    return answered(create_api.sync_detailed(room_name=room, client=client, body=item), SkillRead)


def list_skills(client: Client, room: str) -> SkillListResponse:
    """The room's skills, most recently updated first."""
    from mycelium.client import answered
    from mycelium_backend_client.api.skills import (
        list_skills_api_rooms_room_name_skills_get as list_api,
    )
    from mycelium_backend_client.models import SkillListResponse

    return answered(list_api.sync_detailed(room_name=room, client=client), SkillListResponse)


def get_skill(client: Client, room: str, name: str) -> SkillRead:
    """One skill by name. A name the room doesn't have raises a 404 :class:`HubError`."""
    from mycelium.client import answered
    from mycelium_backend_client.api.skills import (
        get_skill_api_rooms_room_name_skills_name_get as get_api,
    )
    from mycelium_backend_client.models import SkillRead

    return answered(get_api.sync_detailed(room_name=room, name=name, client=client), SkillRead)


def remove_skill(client: Client, room: str, name: str) -> bool:
    """Delete a skill: ``False`` when the room has no such skill."""
    from mycelium_backend_client.api.skills import (
        delete_skill_api_rooms_room_name_skills_name_delete as delete_api,
    )

    resp = delete_api.sync_detailed(room_name=room, name=name, client=client)
    if resp.status_code == 404:  # noqa: PLR2004
        return False
    if resp.status_code >= 400:  # noqa: PLR2004
        raise HubError(resp.status_code, resp.content)
    return True
