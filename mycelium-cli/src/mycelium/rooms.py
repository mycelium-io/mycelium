# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""Rooms on the hub: listing, creating and deleting them, who is in one, and
what the room's sessions and wakes say.

``mycelium room ...`` and the commands that look a room up send these. Each
takes a generated client; a refusal raises :class:`~mycelium.exceptions.HubError`.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from mycelium.exceptions import HubError

if TYPE_CHECKING:
    from mycelium_backend_client import Client
    from mycelium_backend_client.models import (
        A2ABridgeState,
        ParticipantListResponse,
        RoomMembers,
        RoomPresenceRead,
        RoomRead,
        RoomReindexRead,
        WakeOutcome,
        WakeRecord,
    )


def list_rooms(
    client: Client, *, name: str | None = None, limit: int | None = None, viewer: str | None = None
) -> list[RoomRead]:
    """The rooms listed for the caller, newest first: every shared room, and
    ``viewer``'s private ones. ``name`` narrows it to that room."""
    from mycelium.client import answered
    from mycelium_backend_client.api.rooms import list_rooms_api_rooms_get as list_api
    from mycelium_backend_client.types import UNSET

    resp = list_api.sync_detailed(
        client=client,
        name=name if name is not None else UNSET,
        limit=limit if limit is not None else UNSET,
        viewer=viewer if viewer is not None else UNSET,
    )
    return answered(resp, list)


def create_room(
    client: Client, name: str, *, public: bool = True, owner: str | None = None
) -> RoomRead:
    """Make a room. A private room is listed only for its ``owner``."""
    from mycelium.client import answered
    from mycelium_backend_client.api.rooms import create_room_api_rooms_post as create_api
    from mycelium_backend_client.models import RoomCreate, RoomRead

    body = RoomCreate(name=name, is_public=public, owner=None if public else owner)
    return answered(create_api.sync_detailed(client=client, body=body), RoomRead)


def delete_room(client: Client, room: str) -> None:
    """Delete a room and everything in it."""
    from mycelium_backend_client.api.rooms import (
        delete_room_api_rooms_room_name_delete as delete_api,
    )

    resp = delete_api.sync_detailed(room_name=room, client=client)
    if resp.status_code >= 400:  # noqa: PLR2004
        raise HubError(resp.status_code, resp.content)


def reindex(client: Client, room: str) -> RoomReindexRead | None:
    """Have the hub rebuild the room's search index: what it did, or ``None``
    when it turned the request down as invalid."""
    from mycelium.client import answered
    from mycelium_backend_client.api.rooms import (
        reindex_room_api_rooms_room_name_reindex_post as reindex_api,
    )
    from mycelium_backend_client.models import RoomReindexRead

    resp = reindex_api.sync_detailed(room, client=client)
    return None if resp.status_code == 422 else answered(resp, RoomReindexRead)  # noqa: PLR2004


def members(client: Client, room: str) -> RoomMembers:
    """Everyone who is a member of the room, present or not."""
    from mycelium.client import answered
    from mycelium_backend_client.api.members import (
        list_members_api_rooms_room_name_members_get as members_api,
    )
    from mycelium_backend_client.models import RoomMembers

    return answered(members_api.sync_detailed(room, client=client), RoomMembers)


def presence(client: Client, room: str) -> RoomPresenceRead:
    """Who is present in the room now, and the floors held in its threads."""
    from mycelium.client import answered
    from mycelium_backend_client.api.sessions import (
        list_members_api_rooms_room_name_sessions_members_get as presence_api,
    )
    from mycelium_backend_client.models import RoomPresenceRead

    return answered(presence_api.sync_detailed(room, client=client), RoomPresenceRead)


def sessions(client: Client, room: str) -> ParticipantListResponse:
    """The room's open sessions: who joined, and with what intent."""
    from mycelium.client import answered
    from mycelium_backend_client.api.sessions import (
        list_sessions_api_rooms_room_name_sessions_get as sessions_api,
    )
    from mycelium_backend_client.models import ParticipantListResponse

    return answered(sessions_api.sync_detailed(room, client=client), ParticipantListResponse)


def push_herdr_presence(client: Client, room: str, body: dict[str, Any]) -> None:
    """Tell the hub which of the room's members herdr has running on this machine."""
    from mycelium_backend_client.api.sessions import (
        push_herdr_presence_api_rooms_room_name_sessions_herdr_presence_post as presence_api,
    )
    from mycelium_backend_client.models import HerdrPresenceBody

    resp = presence_api.sync_detailed(room, client=client, body=HerdrPresenceBody.from_dict(body))
    if resp.status_code >= 400:  # noqa: PLR2004
        raise HubError(resp.status_code, resp.content)


def drain_herdr_wakes(client: Client, room: str, source: str | None) -> list[dict[str, Any]]:
    """Take the room's queued herdr wakes off the hub, for the agents ``source``
    reported. Taking them empties the queue.

    Each wake comes back as its raw record, so one this side's model can't
    read costs only that wake, not the rest.
    """
    from mycelium.client import sent_unparsed
    from mycelium_backend_client.api.sessions import (
        drain_herdr_wakes_api_rooms_room_name_sessions_herdr_wakes_get as wakes_api,
    )
    from mycelium_backend_client.types import UNSET

    resp = sent_unparsed(wakes_api, client, room, source=source if source is not None else UNSET)
    if resp.status_code >= 400:  # noqa: PLR2004
        raise HubError(resp.status_code, resp.content)
    return resp.json().get("wakes") or []


def report_wake_outcomes(client: Client, room: str, outcomes: list[WakeOutcome]) -> None:
    """Tell the hub what became of the wakes a pass drained, for its wake log."""
    from mycelium.client import sent_unparsed
    from mycelium_backend_client.api.sessions import (
        report_herdr_wakes_api_rooms_room_name_sessions_herdr_wakes_outcomes_post as report_api,
    )
    from mycelium_backend_client.models import WakeOutcomes

    # Told once the hub takes it; what it counts back isn't read.
    resp = sent_unparsed(report_api, client, room, body=WakeOutcomes(outcomes=outcomes))
    if resp.status_code >= 400:  # noqa: PLR2004
        raise HubError(resp.status_code, resp.content)


def wakes(client: Client, room: str, *, limit: int, agent: str | None = None) -> list[WakeRecord]:
    """The wakes the room recorded, newest first, for ``agent`` when given."""
    from mycelium.client import answered
    from mycelium_backend_client.api.sessions import (
        list_wakes_api_rooms_room_name_sessions_wakes_get as wakes_api,
    )
    from mycelium_backend_client.types import UNSET

    resp = wakes_api.sync_detailed(
        room, client=client, limit=limit, agent=agent.lstrip("@") if agent else UNSET
    )
    return answered(resp, list)


def a2a_state(client: Client, room: str) -> A2ABridgeState:
    """What the room's A2A bridge has seen: bridged agents, exchanges, inbound calls."""
    from mycelium.client import answered
    from mycelium_backend_client.api.a2a import a2a_state_api_rooms_room_name_a2a_state_get
    from mycelium_backend_client.models import A2ABridgeState

    resp = a2a_state_api_rooms_room_name_a2a_state_get.sync_detailed(room, client=client)
    return answered(resp, A2ABridgeState)
