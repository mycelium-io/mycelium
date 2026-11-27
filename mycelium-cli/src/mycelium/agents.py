# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""A room's agents on the hub: their manifests, who is present, and the
controls the hub relays to the machine running one (pause, resume, stop,
start, keep, rename), plus join codes and A2A agents.

``mycelium agent ...``, ``engine``, ``herdr`` and the board send these. An
agent's manifest is the memory ``agents/<handle>``: YAML the hub stores like
any other memory. Each request takes a generated client; a refusal raises
:class:`~mycelium.exceptions.HubError`. Nothing here prints.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

import yaml
from pydantic import ValidationError

from mycelium.exceptions import HubError
from mycelium.protocol import AgentManifest

if TYPE_CHECKING:
    from mycelium.config import MyceliumConfig
    from mycelium_backend_client import Client
    from mycelium_backend_client.models import (
        AgentControlRead,
        AgentRead,
        AgentRenameRead,
        AgentsControlRead,
        AgentsRunningRead,
        JoinRead,
        MemoryRead,
    )

_log = logging.getLogger(__name__)

#: The tag every manifest is written with.
MANIFEST_TAG = "agent-manifest"


# ── manifests ─────────────────────────────────────────────────────────────────


def manifest_from_yaml(handle: str, body: str, source: str) -> AgentManifest | None:
    """Parse a manifest body into an :class:`AgentManifest`, or ``None``.

    ``None`` covers both "empty body" and "body present but unreadable"
    (callers can't tell the difference from the return value), but every
    unreadable case is logged at WARNING so it never fails silently. Without
    this, bad YAML or a schema mismatch looks identical to "agent not
    registered" and the user re-runs ``agent create`` over their own broken
    manifest. *source* names where the body came from (a file path, or the
    memory key on the hub) so the warning points at something actionable.
    """
    try:
        data = yaml.safe_load(body) or {}
    except yaml.YAMLError as exc:
        _log.warning("manifest %s: invalid YAML: %s", source, exc)
        return None
    if not isinstance(data, dict):
        _log.warning("manifest %s: expected a YAML mapping, got %s", source, type(data).__name__)
        return None
    data.setdefault("handle", handle)
    try:
        return AgentManifest(**data)
    except ValidationError as exc:
        _log.warning("manifest %s: schema validation failed: %s", source, exc)
        return None


def manifest_yaml(manifest: AgentManifest) -> str:
    """The YAML a manifest is stored as."""
    body = manifest.model_dump(exclude={"handle"})
    return yaml.safe_dump(body, sort_keys=False, default_flow_style=False).strip()


def memory_body(record: MemoryRead) -> str | None:
    """The stored text of a memory, wherever the backend put it.

    The text lands in one of three places depending on how the backend
    serialized the memory: prefer the already-flattened ``content_text``, then a
    plain-string ``value``, then the ``text`` inside a structured ``value``.
    """
    content_text = record.content_text
    if isinstance(content_text, str) and content_text:
        return content_text

    value = record.value
    if isinstance(value, str):
        return value or None
    text = value.additional_properties.get("text")
    if isinstance(text, str) and text:
        return text
    return None


def memory_text(client: Client, room: str, key: str) -> str | None:
    """One memory's stored text from the hub, or ``None`` if it has none.

    A missing memory is ``None``; a hub that is unreachable raises, so no caller
    can mistake "couldn't look" for "not there".
    """
    from mycelium.memory import read_memory

    try:
        result = read_memory(client, room, key)
    except HubError as exc:
        # A 404 is "not there".
        if exc.status_code == 404:  # noqa: PLR2004
            return None
        raise
    return memory_body(result)


def load_manifest(client: Client, room: str, handle: str) -> AgentManifest | None:
    """An agent's manifest from the hub.

    ``None`` means the hub has no readable manifest for *handle*. Transport and
    HTTP failures propagate, so the caller reports an unreachable hub rather
    than printing "no agent named …" for a room it never managed to read.
    """
    key = f"agents/{handle}"
    body = memory_text(client, room, key)
    if not body:
        return None
    return manifest_from_yaml(handle, body, key)


def room_manifests(room: str, *, client: Client | None = None) -> list[AgentManifest]:
    """Every agent manifest registered in a room (skips notes + log children).

    Resolved against the hub's memory API, the one store: a spoke keeps no local
    ``.mycelium/`` replica, so the filesystem is not the room. An unreachable hub
    raises rather than returning an empty list — an empty answer means "no
    agents", never "couldn't look".

    Pass *client* to share one hub session across rooms.
    """
    from mycelium.memory import list_memories

    if client is None:
        from mycelium.client import typed_client
        from mycelium.config import MyceliumConfig

        with typed_client(MyceliumConfig.load()) as own_client:
            return room_manifests(room, client=own_client)

    out: list[AgentManifest] = []
    for record in list_memories(client, room, prefix="agents/", limit=500):
        key = record.key
        handle = key.removeprefix("agents/")
        if not handle or "/" in handle:
            continue
        body = memory_body(record)
        if not body:
            continue
        m = manifest_from_yaml(handle, body, key)
        if m is not None:
            out.append(m)
    return out


def owned_agents(*, owner: str) -> list[tuple[str, AgentManifest]]:
    """Agents owned by ``owner``, across every room on the hub."""
    from mycelium.client import typed_client
    from mycelium.config import MyceliumConfig
    from mycelium.rooms import list_rooms

    owner = owner.strip().lstrip("@").lower()
    owned: list[tuple[str, AgentManifest]] = []
    with typed_client(MyceliumConfig.load()) as client:
        for room in list_rooms(client):
            room_name = room.name
            if not room_name:
                continue
            for m in room_manifests(room_name, client=client):
                if m.owner == owner:
                    owned.append((room_name, m))
    return owned


def save_manifest(client: Client, room: str, manifest: AgentManifest, created_by: str) -> int:
    """Write an agent's manifest to the hub, which registers it, and return its
    version."""
    from mycelium.client import answered
    from mycelium_backend_client.api.memory import (
        create_memories_api_rooms_room_name_memory_post as create_api,
    )
    from mycelium_backend_client.models import MemoryBatchCreate, MemoryCreate

    # embed=False: a manifest is a registry/config entry, not room knowledge.
    # Embedding it pollutes `memory search` (and synthesis) with roster noise.
    item = MemoryCreate(
        key=manifest.memory_key,
        value=manifest_yaml(manifest),
        created_by=created_by,
        embed=False,
        tags=[MANIFEST_TAG],
    )
    batch = MemoryBatchCreate(items=[item])
    saved = answered(create_api.sync_detailed(room_name=room, client=client, body=batch), list)
    return (saved[0].version or 1) if saved else 1


def delete_manifest(client: Client, room: str, key: str) -> None:
    """Remove an agent's manifest from the hub. One the hub no longer has
    counts as removed."""
    from mycelium_backend_client.api.memory import (
        delete_memory_api_rooms_room_name_memory_key_delete as delete_api,
    )

    resp = delete_api.sync_detailed(room_name=room, key=key, client=client)
    if resp.status_code >= 400 and resp.status_code != 404:  # noqa: PLR2004
        raise HubError(resp.status_code, resp.content)


def is_resident(config: MyceliumConfig, room: str, handle: str) -> bool:
    """True if a runtime is currently present in the room for ``handle``.

    Best-effort: queries the backend's live presence set (server-held ``await``
    leases and herdr members). A network/parse failure returns ``False`` so the
    caller falls back to the honest "not resident, queued" message rather than
    claiming liveness it can't confirm.
    """
    from mycelium.client import typed_client
    from mycelium.rooms import presence

    try:
        with typed_client(config, timeout=5.0, raise_on_unexpected_status=False) as client:
            members = presence(client, room).members
    except Exception:  # noqa: BLE001
        return False
    norm = handle.lstrip("@").lower()
    return any(m.handle.lstrip("@").lower() == norm for m in members)


# ── what the hub does to an agent ─────────────────────────────────────────────


def create_a2a(client: Client, room: str, body: dict[str, Any]) -> AgentRead:
    """Register a remote A2A endpoint as a member of the room."""
    from mycelium.client import answered
    from mycelium_backend_client.api.a2a import (
        create_a2a_agent_api_rooms_room_name_a2a_agents_post as create_a2a_api,
    )
    from mycelium_backend_client.models import A2AAgentCreate, AgentRead

    resp = create_a2a_api.sync_detailed(room, client=client, body=A2AAgentCreate.from_dict(body))
    if resp.status_code != 201:  # noqa: PLR2004
        raise HubError(resp.status_code, resp.content)
    return answered(resp, AgentRead)


def invite(client: Client, room: str, body: dict[str, Any]) -> JoinRead:
    """A single-use join code for one member of the room."""
    from mycelium.client import answered
    from mycelium_backend_client.api.joins import (
        create_invite_api_rooms_room_name_invites_post as invite_api,
    )
    from mycelium_backend_client.models import InviteCreate, JoinRead

    resp = invite_api.sync_detailed(room, client=client, body=InviteCreate.from_dict(body))
    return answered(resp, JoinRead)


def rename(client: Client, room: str, old: str, new: str, by: str | None) -> AgentRenameRead:
    """Rename an agent, with what it holds; a running one restarts under the new name."""
    from mycelium.client import answered
    from mycelium_backend_client.api.agents import (
        rename_agent_api_rooms_room_name_agents_handle_rename_post as rename_api,
    )
    from mycelium_backend_client.models import AgentRename, AgentRenameRead

    body = AgentRename.from_dict({"to": new, "by": by})
    return answered(rename_api.sync_detailed(room, old, client=client, body=body), AgentRenameRead)


def control(
    client: Client, room: str, handle: str, verb: str, *, by: str | None, close: bool = False
) -> AgentControlRead:
    """``pause``, ``resume``, ``stop`` or ``start`` one agent, through the
    machine running it."""
    from mycelium.client import answered
    from mycelium_backend_client.api.agents import (
        pause_agent_api_rooms_room_name_agents_handle_pause_post as pause_api,
    )
    from mycelium_backend_client.api.agents import (
        resume_agent_api_rooms_room_name_agents_handle_resume_post as resume_api,
    )
    from mycelium_backend_client.api.agents import (
        start_agent_api_rooms_room_name_agents_handle_start_post as start_api,
    )
    from mycelium_backend_client.api.agents import (
        stop_agent_api_rooms_room_name_agents_handle_stop_post as stop_api,
    )
    from mycelium_backend_client.models import AgentControl, AgentControlRead

    api = {"pause": pause_api, "resume": resume_api, "stop": stop_api, "start": start_api}[verb]
    resp = api.sync_detailed(
        room, handle, client=client, body=AgentControl.from_dict({"by": by, "close": close})
    )
    return answered(resp, AgentControlRead)


def control_mine(
    client: Client, verb: str, *, by: str | None, room: str | None = None
) -> AgentsControlRead:
    """``pause`` or ``resume`` every agent ``by`` owns, in ``room`` when given."""
    from mycelium.client import answered
    from mycelium_backend_client.api.agents import (
        pause_mine_api_agents_pause_post as pause_mine_api,
    )
    from mycelium_backend_client.api.agents import (
        resume_mine_api_agents_resume_post as resume_mine_api,
    )
    from mycelium_backend_client.models import AgentsControl, AgentsControlRead

    api = {"pause": pause_mine_api, "resume": resume_mine_api}[verb]
    resp = api.sync_detailed(client=client, body=AgentsControl.from_dict({"by": by, "room": room}))
    return answered(resp, AgentsControlRead)


def running(client: Client, owner: str) -> AgentsRunningRead:
    """Every agent ``owner`` has, with the state each is in."""
    from mycelium.client import answered
    from mycelium_backend_client.api.agents import (
        running_of_mine_api_agents_running_get as running_api,
    )
    from mycelium_backend_client.models import AgentsRunningRead

    return answered(running_api.sync_detailed(client=client, owner=owner), AgentsRunningRead)


def keep(client: Client, room: str, handle: str, *, by: str | None, on: bool) -> AgentControlRead:
    """Keep an agent running when agents are stopped in bulk, or stop keeping it."""
    from mycelium.client import answered
    from mycelium_backend_client.api.agents import (
        keep_agent_api_rooms_room_name_agents_handle_keep_post as keep_api,
    )
    from mycelium_backend_client.models import AgentControlRead, AgentKeep

    resp = keep_api.sync_detailed(
        room, handle, client=client, body=AgentKeep.from_dict({"by": by, "keep": on})
    )
    return answered(resp, AgentControlRead)
