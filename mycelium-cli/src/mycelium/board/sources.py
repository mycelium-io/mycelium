# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""Every source the board and the room's log are drawn from, read from the hub
in one pass, with how each read went.

``mycelium board`` and ``mycelium room log`` project these. A source that
can't be read contributes nothing rather than failing the whole read; what
went wrong is kept in :class:`HubHealth`.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

import httpx

from mycelium.board.model import LIVE_NAMESPACES

if TYPE_CHECKING:
    from mycelium_backend_client import Client
    from mycelium_backend_client.types import Response


@dataclass
class HubHealth:
    """How the read went: which sources answered, which failed, and why.

    Distinguishes a genuinely unreachable hub from an authenticated hub
    refusing a request or a room that does not exist, so a partial or failed
    read is reported as an error rather than drawn as a quiet, empty board.
    """

    #: Sources that answered with data, by name.
    ok: list[str] = field(default_factory=list)
    #: Sources that failed, name to the reason.
    failed: dict[str, str] = field(default_factory=dict)
    #: Sources the hub answered at all, whatever it said. A refusal is an answer:
    #: it means the hub is running and the reader's problem is a credential, not
    #: a network.
    answered: list[str] = field(default_factory=list)

    @property
    def reachable(self) -> bool:
        """Whether there is enough to draw anything."""
        return bool(self.ok)

    @property
    def note(self) -> str | None:
        """The one line worth printing above a board, or ``None`` when all is well."""
        if not self.failed:
            return None
        if self.ok:
            missing = ", ".join(sorted(self.failed))
            total = len(self.ok) + len(self.failed)
            return f"Incomplete: {len(self.failed)} of {total} sources failed ({missing})"
        if self.answered:
            # The hub is there and said no. Sending the reader to check their
            # network here costs them the time it takes to rule it out.
            reason = next(iter(self.failed.values()))
            return f"Hub refused every request ({reason})"
        return f"Hub unreachable: {next(iter(self.failed.values()))}"


#: The most tasks one board namespace is read for.
ROWS_PER_NAMESPACE = 1000


def read_sources(
    client: Client, room: str, *, rows: bool = False
) -> tuple[dict[str, Any], HubHealth]:
    """Every source the log and the board share, read once, as plain records.

    The log's memories are the room's most recently changed, of any kind. The
    board's (``rows``) are every memory in its namespaces, however long since
    it changed: an open task nobody has touched lately is still open.
    """
    from mycelium_backend_client.api.agents import list_agents_api_rooms_room_name_agents_get
    from mycelium_backend_client.api.board import read_board_api_rooms_room_name_board_get
    from mycelium_backend_client.api.episodes import (
        list_episodes_api_rooms_room_name_episodes_get,
    )
    from mycelium_backend_client.api.memory import list_memories_api_rooms_room_name_memory_get
    from mycelium_backend_client.api.messages import (
        list_messages_api_rooms_room_name_messages_get,
    )
    from mycelium_backend_client.api.sessions import (
        list_members_api_rooms_room_name_sessions_members_get,
    )
    from mycelium_backend_client.api.status import get_room_status_api_rooms_room_name_status_get

    health = HubHealth()

    def get(read: Callable[..., Response[Any]], default: Any, label: str, **params: Any) -> Any:
        try:
            resp = read(room, client=client, **params)
        except httpx.HTTPError as exc:
            health.failed[label] = type(exc).__name__
            return default
        except (ValueError, KeyError, TypeError):
            # The answer didn't parse as what the spec says this route returns.
            health.answered.append(label)
            health.failed[label] = "malformed response"
            return default
        # The hub answered, whatever it said. A refusal is a different problem
        # from a hub that is not there, and the reader fixes it differently.
        health.answered.append(label)
        if resp.status_code >= 400:  # noqa: PLR2004
            health.failed[label] = f"HTTP {resp.status_code}"
            return default
        health.ok.append(label)
        # The projection, the log and ``--json`` read the hub's records as data,
        # so each answer is handed on as its record: checked against the spec on
        # the way in, then the wire's own shape.
        parsed = resp.parsed
        if isinstance(parsed, list):
            return [item.to_dict() for item in parsed]
        return parsed.to_dict() if hasattr(parsed, "to_dict") else parsed

    list_memories = list_memories_api_rooms_room_name_memory_get.sync_detailed
    episodes = get(list_episodes_api_rooms_room_name_episodes_get.sync_detailed, {}, "episodes")
    if rows:
        memories = []
        for namespace in LIVE_NAMESPACES:
            listed = get(
                list_memories, [], f"{namespace}/", prefix=f"{namespace}/",
                limit=ROWS_PER_NAMESPACE,
            )  # fmt: skip
            memories += listed if isinstance(listed, list) else []
    else:
        memories = get(list_memories, [], "memory", limit=50)
    # What the tools the room points at say. A read never fetches hub-side,
    # so this costs a cache lookup, not a round trip to GitHub.
    upstream = get(get_room_status_api_rooms_room_name_status_get.sync_detailed, None, "status")
    agents = get(list_agents_api_rooms_room_name_agents_get.sync_detailed, [], "agents")
    members = get(
        list_members_api_rooms_room_name_sessions_members_get.sync_detailed, {}, "members"
    )
    messages = get(
        list_messages_api_rooms_room_name_messages_get.sync_detailed, {}, "messages", limit=300
    )
    # The epics, worked out by the hub, so this draws what the app draws.
    epics = get(read_board_api_rooms_room_name_board_get.sync_detailed, None, "board")

    return (
        {
            "episodes": (episodes or {}).get("episodes", []) if isinstance(episodes, dict) else [],
            "memories": memories if isinstance(memories, list) else [],
            "agents": agents if isinstance(agents, list) else [],
            "members": (members or {}).get("members", []) if isinstance(members, dict) else [],
            "messages": (messages or {}).get("messages", []) if isinstance(messages, dict) else [],
            "upstream": upstream if isinstance(upstream, dict) else None,
            "board": epics if isinstance(epics, dict) else None,
        },
        health,
    )
