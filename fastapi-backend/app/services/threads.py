# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""Threads started from a message: a conversation about one message, not a task.

A thread is a memory at ``threads/<slug>``, named after the message's first
line, with ``from: <message id>`` in its frontmatter. Like every memory it is
bound to an episode when it is written, so replies, ``respond --task``,
mentions, wakes and search work the way they do in a task's thread. It is no
board row: no one holds it and it has no status, so the board never shows it
and starting one raises no ``filed`` notice.

What the line under the message says (how many replies, who, the newest one)
is worked out on read from the room's transcript, never stored: a reply
rewriting the thread's file would bump its version and announce a memory
change on every message.
"""

from __future__ import annotations

from typing import Any

from app.services import message_format

#: Where threads live. Not a board namespace (``tasks.BOARD_NAMESPACES``).
THREADS_NAMESPACE = "threads"
#: The frontmatter naming the message a thread was started from.
FROM_META = "from"
#: The longest a thread's name is, taken from its message's first line.
TITLE_CHARS = 80
#: How many of a thread's newest repliers the list carries.
REPLIERS = 3


def is_message_thread(key: str) -> bool:
    """Whether ``key`` names a thread started from a message."""
    return key.split("/", 1)[0] == THREADS_NAMESPACE


def title_of(text: str) -> str:
    """A thread's name: its message's first line, at most :data:`TITLE_CHARS`
    characters, cut on a word when one is near the end."""
    line = next((ln.strip() for ln in text.splitlines() if ln.strip()), "")
    line = line.lstrip("#").strip()
    if len(line) <= TITLE_CHARS:
        return line or "Thread"
    head = line[:TITLE_CHARS]
    space = head.rfind(" ")
    return (head[:space] if space > TITLE_CHARS * 0.6 else head).rstrip() + "…"


def message_in_room(room: str, message_id: str) -> Any | None:
    """The message ``message_id`` names in the room's own channel (not inside a
    thread), or ``None`` when there is none."""
    from app.services.persister import prose_messages

    for message in prose_messages(room):
        if str(message.id) == message_id:
            return message if message_format.is_live_episode(room, message.episode) else None
    return None


def thread_of_message(room: str, message_id: str) -> str | None:
    """The key of the thread already started from ``message_id``, if there is one."""
    from app.services.filesystem import get_room_dir, list_memory_files

    for key, meta, _content in list_memory_files(
        get_room_dir(room), prefix=f"{THREADS_NAMESPACE}/", limit=None
    ):
        if str(meta.get(FROM_META) or "") == message_id:
            return key
    return None


def free_key(room: str, title: str, *, namespace: str = THREADS_NAMESPACE) -> str:
    """A key in ``namespace`` for ``title`` that no memory in the room has yet,
    so a write there makes a memory rather than replacing one."""
    from app.services.filesystem import get_room_dir, read_memory_file
    from app.services.tasks import slugify

    base = f"{namespace}/{slugify(title)}"
    key, n = base, 2
    while read_memory_file(get_room_dir(room), key) is not None:
        key, n = f"{base}-{n}", n + 1
    return key


def replies(room: str) -> dict[str, dict[str, Any]]:
    """What each thread in the room has had said in it, by episode URN:
    ``replies``, ``last_reply_at``, the newest ``repliers`` (newest first) and
    ``last_reply`` (its first line). One pass over the transcript the hub
    already holds parsed; it counts what a task's latest line counts
    (``board.latest_lines``): people's and agents' prose, not an engine's."""
    from app.services.board import _first_line as first_line
    from app.services.board import is_report
    from app.services.persister import prose_messages

    seen: dict[str, dict[str, Any]] = {}
    reported: dict[str, bool] = {}
    for message in prose_messages(room):
        text = message.content if isinstance(message.content, str) else ""
        if not message.episode or not text.strip():
            continue
        sender = message.sender_handle
        if sender not in reported:
            reported[sender] = is_report(room, sender)
        if reported[sender]:
            continue
        found = seen.setdefault(message.episode, {"replies": 0, "repliers": []})
        found["replies"] += 1
        found["last_reply_at"] = message.created_at.isoformat() if message.created_at else None
        found["last_reply"] = first_line(text)
        repliers = found["repliers"]
        if sender in repliers:
            repliers.remove(sender)
        repliers.insert(0, sender)
        del repliers[REPLIERS:]
    return seen
