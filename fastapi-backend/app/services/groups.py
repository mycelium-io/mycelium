# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""``@here`` and ``@all``: mentions of a group of members rather than one.

``@all`` reaches everyone in the room: its people and its agents, never its
engines (an engine summoned with nobody named starts nothing). ``@here`` in a
thread reaches the members taking part in it: whoever has posted there, plus
the task's assignee and whoever holds it, even before they've posted. In the
room's channel, outside any thread, ``@here`` is ``@all``. Neither ever reaches
the one who wrote it.

They take the same three forms a mention of one member does: ``@here`` asks
each member, ``@~here`` names them without asking anything (no wake), and
``@!here`` interrupts the ones that are working.

Who a group reaches is worked out once, when the message is sent
(:func:`resolve`), and kept on the message, so who it asked never changes as
the thread goes on, and every reader of it (wakes, the wake digest, ``await``)
agrees: they read it through :func:`asked_by_groups`. The composer asks the same
question before sending (:func:`members`, behind
``GET /rooms/{room}/mentions/groups``), so who it shows is who is woken.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from typing import Any, Literal

from app.services.agent_registry import norm_handle

#: The group names, which no member can be called.
GROUPS = ("here", "all")

#: The key a sent message keeps its groups' members under, in its content.
CONTENT_KEY = "groups"

Form = Literal["mention", "interrupt", "silent"]
#: How a group asked a member: the loud forms only.
Asked = Literal["mention", "interrupt"]

# The same boundary rule as a mention of one member (``persister._SUMMON_RE``):
# the ``@`` starts the text or follows whitespace, ``(`` or ``<``, and the name
# ends at the first character a handle couldn't have.
_GROUP_RE = re.compile(r"(?:^|(?<=[\s(<]))@([~!]?)(here|all)(?![\w-])")
_FORMS: dict[str, Form] = {"": "mention", "!": "interrupt", "~": "silent"}
#: Which form wins when one message writes a group more than one way.
_STRENGTH: dict[Form, int] = {"silent": 0, "mention": 1, "interrupt": 2}


@dataclass(frozen=True)
class Member:
    """One member a group reaches, as the composer draws it."""

    handle: str
    kind: Literal["agent", "person"]
    #: Its live state when it runs in a herdr pane (``working``, ``idle``...).
    status: str | None
    #: When it last posted in the thread, for ``@here``.
    posted_at: str | None
    #: Why ``@here`` reaches it: it ``posted``, or is the task's ``assignee``
    #: or ``holder``. ``None`` for ``@all``.
    role: Literal["posted", "assignee", "holder"] | None


def parse(text: str) -> dict[str, Form]:
    """The groups ``text`` names, each in the strongest form it's written in.

    Code is quoted, never addressed, as with any mention."""
    from app.services.persister import blank_code

    found: dict[str, Form] = {}
    for prefix, name in _GROUP_RE.findall(blank_code(text)):
        form = _FORMS[prefix]
        if name not in found or _STRENGTH[form] > _STRENGTH[found[name]]:
            found[name] = form
    return found


def _is_thread(room: str, episode: str | None) -> bool:
    from app.services import message_format

    return bool(episode) and episode != message_format.live_episode_urn(room)


def _statuses(room: str) -> dict[str, str]:
    from app.services import room_channels

    out: dict[str, str] = {}
    for handle, p in room_channels.manager.presence(room).items():
        name = norm_handle(handle)
        if name and p.status:
            out[name] = p.status
    return out


def _everyone(room: str) -> dict[str, Literal["agent", "person"]]:
    """Each of the room's people and agents, by handle; never its engines."""
    from app.services import room_people

    roster = room_people.roster(room)
    out: dict[str, Literal["agent", "person"]] = {}
    for entry in roster["people"]:
        if name := norm_handle(entry.get("handle")):
            out[name] = "person"
    for entry in roster["agents"]:
        if name := norm_handle(entry.get("handle")):
            out[name] = "agent"
    return out


def _thread_posters(room: str, episode: str) -> dict[str, str]:
    """Who has posted in the thread ``episode``, each with when they last did."""
    from app.services import persister

    last: dict[str, str] = {}
    for m in persister.prose_messages(room):
        if m.episode != episode:
            continue
        if name := norm_handle(m.sender_handle):
            last[name] = m.created_at.isoformat()
    return last


def _task_people(room: str, episode: str) -> dict[str, Literal["assignee", "holder"]]:
    """The assignee and the holder of the task whose thread ``episode`` is."""
    from app.services import assignments, tasks
    from app.services.filesystem import get_room_dir, read_memory_file

    row = tasks.row_of_episode(room, episode)
    if row is None:
        return {}
    found = read_memory_file(get_room_dir(room), row[0])
    meta: dict[str, Any] = found[0] if found else {}
    out: dict[str, Literal["assignee", "holder"]] = {}
    if holder := norm_handle(assignments.holder(meta, datetime.now(UTC))):
        out[holder] = "holder"
    if (assignee := norm_handle(meta.get(assignments.ASSIGNEE_FIELD))) and assignee not in out:
        out[assignee] = "assignee"
    return out


def members(room: str, *, episode: str | None, sender: str | None) -> dict[str, list[Member]]:
    """Who ``@here`` and ``@all`` reach for ``sender`` writing in ``episode``.

    ``episode`` is the thread the message is written in; ``None`` (or the room's
    own) is the room's channel, where ``@here`` is ``@all``.
    """
    me = norm_handle(sender)
    everyone = _everyone(room)
    status = _statuses(room)

    def member(handle: str, *, posted_at: str | None = None, role: Any = None) -> Member:
        return Member(handle, everyone[handle], status.get(handle), posted_at, role)

    all_ = [member(h) for h in sorted(everyone) if h != me]
    if not _is_thread(room, episode):
        return {"here": all_, "all": all_}
    assert episode is not None
    posted = _thread_posters(room, episode)
    task = _task_people(room, episode)
    here: list[Member] = []
    for handle in [*posted, *(h for h in task if h not in posted)]:
        if handle == me or handle not in everyone:
            continue
        role = "posted" if handle in posted else task[handle]
        here.append(member(handle, posted_at=posted.get(handle), role=role))
    return {"here": here, "all": all_}


def resolve(
    room: str, *, text: str, episode: str | None, sender: str | None
) -> dict[str, Any] | None:
    """What a message's groups reach, to keep on the message; ``None`` when it names none.

    ``asked``: every member a loud group asks (``@here``, ``@!all``...), each
    with ``mention`` or ``interrupt``. ``named``: every member a silent one
    (``@~here``) names without asking. A member asked by one group and named
    by another is asked.
    """
    forms = parse(text)
    if not forms:
        return None
    reached = members(room, episode=episode, sender=sender)
    asked: dict[str, Form] = {}
    named: set[str] = set()
    for name, form in forms.items():
        for m in reached[name]:
            if form == "silent":
                named.add(m.handle)
            elif form == "interrupt" or asked.get(m.handle) != "interrupt":
                asked[m.handle] = form
    return {
        "written": dict(forms),
        "asked": asked,
        "named": sorted(named - set(asked)),
    }


def on_message(
    room: str, *, text: str, episode: str | None, sender: str | None
) -> tuple[dict[str, Any], list[str]]:
    """What a message being sent carries for its groups: the ``extra`` its
    content is serialized with (its text, and what its groups reached when
    it names any), and the members those groups ask, in order."""
    reached = resolve(room, text=text, episode=episode, sender=sender)
    if reached is None:
        return {"content": text}, []
    return {"content": text, CONTENT_KEY: reached}, list(reached["asked"])


def asked_by_groups(content: dict[str, Any]) -> dict[str, Asked]:
    """Whom a sent message's groups asked, and how, as kept on it by :func:`resolve`."""
    kept = content.get(CONTENT_KEY)
    if not isinstance(kept, dict):
        return {}
    asked = kept.get("asked")
    if not isinstance(asked, dict):
        return {}
    out: dict[str, Asked] = {}
    for h, f in asked.items():
        if isinstance(h, str) and f == "interrupt":
            out[h] = "interrupt"
        elif isinstance(h, str) and f == "mention":
            out[h] = "mention"
    return out


def as_wire(groups: dict[str, list[Member]]) -> dict[str, Any]:
    """The endpoint's answer: each group's count and members."""
    return {
        name: {"count": len(ms), "members": [asdict(m) for m in ms]} for name, ms in groups.items()
    }
