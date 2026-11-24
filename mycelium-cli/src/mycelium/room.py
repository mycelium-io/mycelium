# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""Mycelium as a library: one room, and the verbs agents use in it.

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

Each method is one call into the module that owns the request, the same one
the CLI's verb sends through: ``mycelium.chat`` for a reply,
``mycelium.board.tasks`` for the board, ``mycelium.memory`` and
``mycelium.files``; ``wait`` is ``await``'s own wait. What comes back is the
hub's own record, as the generated client parses it (``MemoryRead``,
``ReplyRead``, ...). A refusal raises :class:`~mycelium.exceptions.HubError`
(the generated client's ``UnexpectedStatus``), with ``Held`` and ``Waiting``
for a claim the hub turns down; a hub that can't be reached raises
``httpx.HTTPError``.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

from mycelium.exceptions import MyceliumError

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

__all__ = ["Board", "Files", "Memory", "Room"]

#: How long a write waits on the hub.
_WRITE_TIMEOUT_S = 30.0
#: How long an upload waits on the hub.
_UPLOAD_TIMEOUT_S = 300.0


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
            msg = (
                "Say who you're acting as: identity.set('me') once, Room(..., handle='me'), "
                "or MYCELIUM_AGENT_HANDLE."
            )
            raise MyceliumError(msg)
        return self.handle

    def thread(self, task: str) -> str:
        """The thread on ``task`` (a memory key such as ``work/apple-pay``)."""
        from mycelium.board.model import EPISODE_FIELD
        from mycelium.memory import read_memory

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

    def respond(
        self, text: str, *, task: str | None = None, reply_to: AwaitTurn | None = None
    ) -> ReplyRead:
        """Post ``text``: in the room, in ``task``'s thread, or where ``reply_to`` was said.

        ``reply_to`` is a turn :meth:`wait` returned, so an answer lands in the
        thread the question came from.
        """
        from mycelium.chat import reply

        if task and reply_to:
            msg = "Pass task or reply_to, not both."
            raise ValueError(msg)
        if reply_to:
            episode = reply_to.episode
        else:
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
        from mycelium.board.tasks import create_task

        r = self._room
        with r._client() as client:  # noqa: SLF001
            return create_task(
                client,
                r.name,
                title=title,
                handle=r._acting(),  # noqa: SLF001
                body=body,
                assign=assign,
                parent=parent,
            )

    def claim(self, key: str, *, ttl: int | None = None, force: bool = False) -> AssignmentRead:
        """Hold the task ``key`` until you resolve it or hand it back.

        ``ttl`` makes the hold a lease of that many minutes. ``force`` takes it
        while it still waits on other tasks. Raises ``Held`` or ``Waiting``.
        """
        from mycelium.board.tasks import change_assignment

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
        from mycelium.board.tasks import change_assignment

        r = self._room
        with r._client() as client:  # noqa: SLF001
            return change_assignment(
                client,
                r.name,
                "resolve",
                key=key,
                handle=r._acting(),  # noqa: SLF001
            )


class Memory:
    """The room's memories: ``room.memory``."""

    def __init__(self, room: Room) -> None:
        self._room = room

    def get(self, key: str) -> MemoryRead:
        """One memory by key."""
        from mycelium.memory import read_memory

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
        from mycelium.memory import learned, memory_item, save_memory

        r = self._room
        item = memory_item(
            key,
            value,
            handle=r._acting(),  # noqa: SLF001
            tags=tags,
            meta={**(meta or {}), **learned(kind, task, derived_from, still_open=still_open)},
        )
        with r._client() as client:  # noqa: SLF001
            return save_memory(client, r.name, item)

    def search(self, query: str, *, limit: int = 5) -> list[MemorySearchResult]:
        """The memories closest in meaning to ``query``, best first."""
        from mycelium.memory import search_memories

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
        from mycelium.files import upload_file

        r = self._room
        file = Path(path)
        if not file.is_file():
            msg = f"Not a file: {file}"
            raise MyceliumError(msg)
        handle = r._acting()  # noqa: SLF001
        with hub_client(r.config, timeout=_UPLOAD_TIMEOUT_S, handle=handle) as http:
            return upload_file(http, r.name, file, handle)
