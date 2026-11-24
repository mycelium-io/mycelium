# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""Mycelium as a library: the verbs agents use, from Python.

    from mycelium import Room

    room = Room("checkout")
    turn = room.wait(timeout=60)
    room.respond("On it.", task="work/apple-pay")
    task = room.board.new("Ship passkey login", body="Passwords stay as a fallback.")
    room.board.claim(task.key)
    room.memory.set("context/goal", "Launch by Friday")
    room.board.resolve(task.key)

A ``Room`` works out the hub, the room, who you are and your credential the
way the CLI does (``mycelium.caller``): an argument, then the environment,
then the herdr pane, this folder's membership, and this machine's setup.

The CLI's ``respond``, ``board new|claim|resolve``, ``memory get|set|search``
and ``file upload`` send their request through the functions below, and
``Room.wait`` is ``await``'s own wait, so the library and the CLI are one
code path. What comes back is the hub's own record, as the generated client
parses it (``MemoryRead``, ``ReplyRead``, ...). A refusal raises
:class:`HubError` (the generated client's ``UnexpectedStatus``), with
:class:`Held` and :class:`Waiting` for a claim the hub turns down; a hub that
can't be reached raises ``httpx.HTTPError``.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any
from urllib.parse import quote

from mycelium.exceptions import MyceliumError
from mycelium_backend_client.errors import UnexpectedStatus

if TYPE_CHECKING:
    from mycelium.config import MyceliumConfig
    from mycelium_backend_client import Client
    from mycelium_backend_client.models import (
        AssignmentRead,
        AwaitTurn,
        MemoryRead,
        MemorySearchResult,
        ReplyRead,
    )

__all__ = ["Board", "Files", "Held", "HubError", "Memory", "Room", "Waiting"]

#: A refusal from the hub: ``status_code`` and ``content`` say what it answered.
HubError = UnexpectedStatus

#: How long a write waits on the hub.
_WRITE_TIMEOUT_S = 30.0
#: How long an upload waits on the hub.
_UPLOAD_TIMEOUT_S = 300.0


class Held(UnexpectedStatus):
    """A claim refused because someone else holds the row."""

    def __init__(self, key: str, owner: str | None, content: bytes) -> None:
        self.key = key
        self.owner = owner
        super().__init__(409, content)


class Waiting(UnexpectedStatus):
    """A claim refused because the row waits on rows not yet resolved."""

    def __init__(self, key: str, waiting_on: list[str], content: bytes) -> None:
        self.key = key
        self.waiting_on = waiting_on
        super().__init__(409, content)


# ── the requests, shared with the CLI ─────────────────────────────────────────
#
# Each takes a generated client, so the CLI keeps its own session (and its own
# way of saying a hub is down) and the library its own.


def reply(
    client: Client, room: str, handle: str, text: str, episode: str | None = None
) -> ReplyRead:
    """Post ``text`` as ``handle``: into the thread ``episode``, or the room."""
    from mycelium.client import answered
    from mycelium_backend_client.api.participate import (
        post_reply_api_rooms_room_name_reply_post as reply_api,
    )
    from mycelium_backend_client.models import ReplyBody, ReplyRead
    from mycelium_backend_client.types import UNSET

    body = ReplyBody(handle=handle, text=text, episode=episode or UNSET)
    return answered(reply_api.sync_detailed(room, client=client, body=body), ReplyRead)


def create_task(
    client: Client,
    room: str,
    *,
    title: str,
    handle: str,
    body: str | None = None,
    assign: str | None = None,
    parent: str | None = None,
) -> MemoryRead:
    """File a task on the board. ``parent`` is the memory key of the row it is part of."""
    from mycelium.client import answered
    from mycelium_backend_client.api.tasks import create_task_api_rooms_room_name_tasks_post
    from mycelium_backend_client.models import MemoryRead, TaskCreate

    fields: dict[str, Any] = {"title": title, "handle": handle}
    if body and body.strip():
        fields["content"] = body
    if assign:
        fields["assignee"] = assign.lstrip("@")
    if parent:
        fields["parent"] = parent
    resp = create_task_api_rooms_room_name_tasks_post.sync_detailed(
        room, client=client, body=TaskCreate.from_dict(fields)
    )
    return answered(resp, MemoryRead)


def change_assignment(client: Client, room: str, action: str, **fields: Any) -> AssignmentRead:
    """``claim``, ``release`` or ``resolve`` a row through its lease."""
    from mycelium.board.model import WAITING_FIELD
    from mycelium_backend_client.api.assignments import (
        claim_assignment_api_rooms_room_name_assignments_claim_post as claim_api,
    )
    from mycelium_backend_client.api.assignments import (
        release_assignment_api_rooms_room_name_assignments_release_post as release_api,
    )
    from mycelium_backend_client.api.assignments import (
        resolve_assignment_api_rooms_room_name_assignments_resolve_post as resolve_api,
    )
    from mycelium_backend_client.models import AssignmentRead, ClaimBody, ReleaseBody, ResolveBody

    payload = {k: v for k, v in fields.items() if v is not None}
    if action == "claim":
        resp = claim_api.sync_detailed(room, client=client, body=ClaimBody.from_dict(payload))
    elif action == "release":
        resp = release_api.sync_detailed(room, client=client, body=ReleaseBody.from_dict(payload))
    elif action == "resolve":
        resp = resolve_api.sync_detailed(room, client=client, body=ResolveBody.from_dict(payload))
    else:
        msg = f"unknown assignment action {action!r}"
        raise ValueError(msg)
    if resp.status_code == 409:  # noqa: PLR2004
        try:
            detail = json.loads(resp.content).get("detail", {})
        except (ValueError, AttributeError):
            detail = {}
        key = str(payload.get("key", ""))
        waiting = detail.get(WAITING_FIELD) if isinstance(detail, dict) else None
        if waiting:
            raise Waiting(key, [str(w) for w in waiting], resp.content)
        raise Held(key, detail.get("owner") if isinstance(detail, dict) else None, resp.content)
    if not isinstance(resp.parsed, AssignmentRead):
        raise UnexpectedStatus(resp.status_code, resp.content)
    return resp.parsed


def check_key(key: str) -> None:
    """Raise ``ValueError``, saying why, for a key the room won't take.

    The hub's path safety is the one rule on a key, and a key is stored as
    typed. The exception: every key under a board namespace is a row, so a
    nested one there would file a row nobody asked for.
    """
    from mycelium.board.model import LIVE_NAMESPACES

    if not key.strip() or "\\" in key or key.endswith("/"):
        msg = f"{key!r} isn't a memory key. Use `/` between its parts, like context/goal."
        raise ValueError(msg)
    category, _, name = key.partition("/")
    if category in LIVE_NAMESPACES and "/" in name:
        joined = "-".join(p for p in name.split("/") if p)
        msg = (
            f"{key} can't have folders: every {category}/ key is a row on the board, "
            f"so it takes one name. Try {category}/{joined}."
        )
        if category == "work":
            msg += " For a part of a task, use `mycelium board new <title> --parent <row>`."
        raise ValueError(msg)


def memory_item(
    key: str,
    value: str,
    *,
    handle: str,
    embed: bool = True,
    tags: list[str] | None = None,
    meta: dict[str, Any] | None = None,
) -> Any:
    """The ``MemoryCreate`` for one write, or ``ValueError`` for a key the room won't take."""
    from mycelium.protocol import MEMORY_CATEGORIES
    from mycelium_backend_client.models import MemoryCreate, MemoryCreateValueType0

    check_key(key)
    category, _, name = key.partition("/")
    if name and category in MEMORY_CATEGORIES:
        # A category key is recorded with when it was written.
        timestamp = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
        structured = MemoryCreateValueType0()
        structured["text"] = value
        structured["logged_at"] = timestamp
        structured["category"] = category
        item = MemoryCreate(
            key=key,
            value=structured,
            created_by=handle,
            embed=embed,
            content_text=f"[{timestamp}] {value}",
            tags=tags,
        )
    else:
        try:
            parsed: Any = json.loads(value)
        except json.JSONDecodeError:
            parsed = value
        item = MemoryCreate(key=key, value=parsed, created_by=handle, embed=embed, tags=tags)
    if meta:
        # Frontmatter rides as an additional property, which the client passes through.
        item["meta"] = meta
    return item


def learned(
    kind: str | None = None,
    task: str | None = None,
    derived_from: list[str] | None = None,
    *,
    still_open: bool = False,
) -> dict[str, Any]:
    """The frontmatter that files a memory in a task's graph of what was learned."""
    meta: dict[str, Any] = {}
    if kind:
        meta["kind"] = kind
    if task:
        meta["task"] = task
    if derived_from:
        meta["derived-from"] = derived_from
    if still_open:
        meta["open"] = True
    return meta


def save_memory(client: Client, room: str, item: Any) -> MemoryRead:
    """Write one memory (an upsert) and return what the hub saved."""
    from mycelium.client import answered
    from mycelium_backend_client.api.memory import (
        create_memories_api_rooms_room_name_memory_post as create_api,
    )
    from mycelium_backend_client.models import MemoryBatchCreate

    resp = create_api.sync_detailed(
        room_name=room, client=client, body=MemoryBatchCreate(items=[item])
    )
    saved = [] if resp.status_code == 422 else answered(resp, list)  # noqa: PLR2004
    if not saved:
        raise UnexpectedStatus(resp.status_code, resp.content)
    return saved[0]


def read_memory(client: Client, room: str, key: str) -> MemoryRead:
    """One memory by key. A key the room doesn't have raises a 404 :class:`HubError`."""
    from mycelium.client import answered
    from mycelium_backend_client.api.memory import (
        get_memory_api_rooms_room_name_memory_key_get as get_api,
    )
    from mycelium_backend_client.models import MemoryRead

    return answered(get_api.sync_detailed(room_name=room, key=key, client=client), MemoryRead)


def search_memories(
    client: Client, room: str, query: str, limit: int = 5
) -> list[MemorySearchResult]:
    """The room's memories closest in meaning to ``query``, best first."""
    from mycelium.client import answered
    from mycelium_backend_client.api.memory import (
        search_memories_api_rooms_room_name_memory_search_post as search_api,
    )
    from mycelium_backend_client.models import MemorySearchRequest, MemorySearchResponse

    body = MemorySearchRequest(query=query, limit=limit)
    found = answered(
        search_api.sync_detailed(room_name=room, client=client, body=body), MemorySearchResponse
    )
    return list(found.results)


def upload_file(http: Any, room: str, path: Path, handle: str | None) -> dict[str, Any]:
    """Add one file to the room through a raw ``httpx`` client, and return its record."""
    with path.open("rb") as fh:
        resp = http.post(
            f"/api/rooms/{quote(room, safe='')}/uploads",
            files={"file": (path.name, fh, "application/octet-stream")},
            data={"created_by": handle or ""},
        )
    if resp.status_code != 201:  # noqa: PLR2004
        raise UnexpectedStatus(resp.status_code, resp.content)
    return resp.json()


# ── the library ───────────────────────────────────────────────────────────────


class Room:
    """One room on a hub, acting as one member.

    ``name``, ``handle`` and ``hub`` default the way the CLI's ``--room``,
    ``--as`` and ``MYCELIUM_API_URL`` do. ``hub`` is that variable: the
    credential this machine holds is sent to it.
    """

    def __init__(
        self, name: str | None = None, *, handle: str | None = None, hub: str | None = None
    ) -> None:
        from mycelium import identity
        from mycelium.cli_options import resolve_room
        from mycelium.config import MyceliumConfig

        self.config: MyceliumConfig = MyceliumConfig.load()
        if hub:
            self.config.server.api_url = hub.rstrip("/")
        self.name: str = resolve_room(self.config, name)
        acting = identity.resolve_actor(self.config, handle, fallback="")
        self.handle: str | None = acting or None
        self.board = Board(self)
        self.memory = Memory(self)
        self.files = Files(self)

    @property
    def hub(self) -> str:
        """The hub this room is read from and written to."""
        return self.config.server.api_url

    def __repr__(self) -> str:
        return f"Room({self.name!r}, handle={self.handle!r}, hub={self.hub!r})"

    def _client(self, timeout: float = _WRITE_TIMEOUT_S) -> Client:
        from mycelium.client import typed_client

        return typed_client(
            self.config, handle=self.handle, timeout=timeout, raise_on_unexpected_status=False
        )

    def _acting(self) -> str:
        if not self.handle:
            msg = "Say who you're acting as: Room(..., handle='me'), or set MYCELIUM_AGENT_HANDLE."
            raise MyceliumError(msg)
        return self.handle

    def thread(self, task: str) -> str:
        """The thread on ``task`` (a memory key such as ``work/apple-pay``)."""
        from mycelium.board.model import EPISODE_FIELD

        with self._client() as client:
            found = read_memory(client, self.name, task)
        episode = found.to_dict().get(EPISODE_FIELD)
        if not episode:
            msg = f"{task} has no thread."
            raise MyceliumError(msg)
        return str(episode)

    def wait(self, timeout: int = 0, *, task: str | None = None) -> AwaitTurn | None:
        """Wait for the next message for you, as ``mycelium await`` does.

        ``timeout`` is seconds (0 waits until one comes); ``None`` when none
        came in time. With ``task``, only that task's thread wakes it. What it
        hands over is marked read once it's here.
        """
        from mycelium.commands.participate import _await_once

        episode = self.thread(task) if task else None
        return _await_once(self.config, self.name, self._acting(), timeout, episode)

    def respond(self, text: str, *, task: str | None = None) -> ReplyRead:
        """Post ``text``, in the room or in ``task``'s thread."""
        episode = self.thread(task) if task else None
        with self._client() as client:
            return reply(client, self.name, self._acting(), text, episode)


class Board:
    """The room's tasks: ``room.board``."""

    def __init__(self, room: Room) -> None:
        self._room = room

    def new(
        self,
        title: str,
        *,
        body: str | None = None,
        assign: str | None = None,
        parent: str | None = None,
    ) -> MemoryRead:
        """File a task. ``assign`` is who it's for; ``parent`` the key of the task it's part of."""
        r = self._room
        with r._client() as client:  # noqa: SLF001
            return create_task(
                client,
                r.name,
                title=title,
                handle=r.handle or "unknown",
                body=body,
                assign=assign,
                parent=parent,
            )

    def claim(self, key: str, *, ttl: int | None = None, force: bool = False) -> AssignmentRead:
        """Hold the task ``key`` until you resolve it or hand it back.

        ``ttl`` makes the hold a lease of that many minutes. ``force`` takes it
        while it still waits on other tasks. Raises :class:`Held` or :class:`Waiting`.
        """
        r = self._room
        with r._client() as client:  # noqa: SLF001
            return change_assignment(
                client,
                r.name,
                "claim",
                key=key,
                handle=r._acting(),  # noqa: SLF001
                ttl_minutes=ttl,
                force=force or None,
            )

    def resolve(self, key: str) -> AssignmentRead:
        """Mark the task ``key`` done."""
        r = self._room
        with r._client() as client:  # noqa: SLF001
            return change_assignment(
                client, r.name, "resolve", key=key, handle=r.handle or "unknown"
            )


class Memory:
    """The room's memories: ``room.memory``."""

    def __init__(self, room: Room) -> None:
        self._room = room

    def get(self, key: str) -> MemoryRead:
        """One memory by key."""
        r = self._room
        with r._client() as client:  # noqa: SLF001
            return read_memory(client, r.name, key)

    def set(
        self,
        key: str,
        value: str,
        *,
        tags: list[str] | None = None,
        meta: dict[str, Any] | None = None,
        kind: str | None = None,
        task: str | None = None,
        derived_from: list[str] | None = None,
        still_open: bool = False,
    ) -> MemoryRead:
        """Write a memory (an upsert: an existing key gets a new version).

        ``kind`` (``fact``, ``finding`` or ``dead-end``), ``task``,
        ``derived_from`` and ``still_open`` file it in the task's graph of
        what was learned, as ``memory set --kind`` does.
        """
        r = self._room
        item = memory_item(
            key,
            value,
            handle=r.handle or "cli-user",
            tags=tags,
            meta={**(meta or {}), **learned(kind, task, derived_from, still_open=still_open)},
        )
        with r._client() as client:  # noqa: SLF001
            return save_memory(client, r.name, item)

    def search(self, query: str, *, limit: int = 5) -> list[MemorySearchResult]:
        """The memories closest in meaning to ``query``, best first."""
        r = self._room
        with r._client() as client:  # noqa: SLF001
            return search_memories(client, r.name, query, limit)


class Files:
    """The room's files: ``room.files``."""

    def __init__(self, room: Room) -> None:
        self._room = room

    def upload(self, path: str | Path) -> dict[str, Any]:
        """Add a file to the room. ``record["name"]`` links it in a message as ``[[uploads/<name>]]``."""
        from mycelium.client import hub_client

        r = self._room
        file = Path(path)
        if not file.is_file():
            msg = f"Not a file: {file}"
            raise MyceliumError(msg)
        with hub_client(r.config, timeout=_UPLOAD_TIMEOUT_S, handle=r.handle) as http:
            return upload_file(http, r.name, file, r.handle)
