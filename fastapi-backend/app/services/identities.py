# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""Who a signed-in person is in a room: a short handle, kept with their sign-in.

A sign-in names a person by its handle claim (``AUTH_HANDLE_CLAIM``), which a
corporate sign-in sets to an email. Used as a handle, that put an email in every
mention, task and message. So the hub keeps each sign-in identity (issuer and
subject) bound to a short handle: the first time, the part of the claim before
the ``@``, or one the person picks when that's taken or isn't a valid handle.
The same sign-in always gets the same handle, and the email is only how they
sign in.

A claim that's already a plain handle is bound as it is, so a hub whose sign-in
says ``sam`` sees no change. The claim a handle was bound from is kept beside
it, so a person's own old (email-shaped) handle still means them, and nobody
else's.
"""

from __future__ import annotations

import json
import re
import threading
from pathlib import Path
from typing import Any

from app.schemas import HANDLE_PATTERN
from app.services.agent_registry import norm_handle
from app.services.filesystem import get_data_dir

#: The bindings' file, in the data folder.
STORE = "identities.json"

_HANDLE = re.compile(HANDLE_PATTERN)
_lock = threading.Lock()


class HandleTaken(ValueError):
    """A handle someone else already has."""


def _path() -> Path:
    return get_data_dir() / STORE


def _key(issuer: str, subject: str) -> str:
    return f"{issuer}\n{subject}"


def _read() -> dict[str, dict[str, Any]]:
    try:
        data = json.loads(_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    bindings = data.get("bindings") if isinstance(data, dict) else None
    return bindings if isinstance(bindings, dict) else {}


def _write(bindings: dict[str, dict[str, Any]]) -> None:
    path = _path()
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps({"bindings": bindings}, indent=2, sort_keys=True) + "\n")
    tmp.replace(path)


def short_of(claimed: str) -> str | None:
    """The handle a claim gives: the part before an ``@``, else the claim,
    or ``None`` when that isn't a valid handle."""
    candidate = norm_handle(claimed.split("@", 1)[0] if "@" in claimed else claimed)
    return candidate if candidate and _HANDLE.match(candidate) and "@" not in candidate else None


def _someone_else_has(handle: str, issuer: str, subject: str, claimed: str) -> bool:
    """Whether ``handle`` is someone else's: bound to another sign-in, or
    already named anywhere rights live, since whoever got it would inherit
    them. Only the person's own claim, already a plain handle, is theirs."""
    me = _key(issuer, subject)
    for key, entry in _read().items():
        if key != me and (entry.get("handle") == handle or entry.get("claimed") == handle):
            return True
    if handle == norm_handle(claimed):
        return False
    from app.services import principals

    return principals.load_user(handle) is not None or _named_anywhere(handle)


def _named_anywhere(handle: str) -> bool:
    """Whether any room names ``handle``: as an agent, an agent's ``owner``
    or ``allow_from``, one of its people or members, or a task's holder or
    assignee. A handle with rights it gives isn't free to hand out."""
    import yaml

    from app.services import assignments, room_people
    from app.services.agent_registry import AGENTS_PREFIX
    from app.services.filesystem import (
        list_memory_files,
        list_room_names,
        read_room_meta,
        room_path,
    )

    def names(value: object) -> bool:
        values = value if isinstance(value, list) else [value]
        return any(norm_handle(v) == handle for v in values)

    for room in list_room_names():
        meta = read_room_meta(room) or {}
        if (
            handle in room_people.handles(room)
            or names(meta.get("owner"))
            or names(meta.get("members"))
        ):
            return True
        for key, fields, content in list_memory_files(room_path(room), limit=None):
            if key.startswith(AGENTS_PREFIX) and "/" not in key.removeprefix(AGENTS_PREFIX):
                if key.removeprefix(AGENTS_PREFIX) == handle:
                    return True
                try:
                    data = yaml.safe_load(content) or {}
                except yaml.YAMLError:
                    continue
                if isinstance(data, dict) and (
                    names(data.get("owner")) or names(data.get("allow_from"))
                ):
                    return True
            elif assignments.assignable(key) and (
                names(fields.get("owner")) or names(fields.get("assignee"))
            ):
                return True
    return False


def resolve(issuer: str, subject: str, claimed: str) -> str | None:
    """This sign-in's handle: the one it's bound to, else the short one its
    claim gives, bound now when nobody else has it. ``None`` when the person
    has to pick one (:func:`pick`)."""
    with _lock:
        bindings = _read()
        entry = bindings.get(_key(issuer, subject))
        if entry:
            return entry["handle"]
        candidate = short_of(claimed)
        if candidate is None or _someone_else_has(candidate, issuer, subject, claimed):
            return None
        bindings[_key(issuer, subject)] = {"handle": candidate, "claimed": norm_handle(claimed)}
        _write(bindings)
        return candidate


def pick(issuer: str, subject: str, claimed: str, handle: str) -> str:
    """Bind this sign-in to ``handle``, picked by the person. Refused when it
    isn't a valid handle, has an ``@`` in it, or someone else has it; a
    sign-in that's already bound keeps its handle."""
    wanted = norm_handle(handle)
    if not wanted or not _HANDLE.match(wanted) or "@" in wanted:
        msg = (
            "A handle is lowercase letters, digits, and . _ or -, starting with a letter or digit."
        )
        raise ValueError(msg)
    with _lock:
        bindings = _read()
        entry = bindings.get(_key(issuer, subject))
        if entry:
            return entry["handle"]
        if _someone_else_has(wanted, issuer, subject, claimed):
            msg = f"@{wanted} is taken. Pick another."
            raise HandleTaken(msg)
        bindings[_key(issuer, subject)] = {"handle": wanted, "claimed": norm_handle(claimed)}
        _write(bindings)
        return wanted


def claimed_by(handle: str) -> str | None:
    """The sign-in claim ``handle`` was bound from, when that differs from it:
    the person's old handle, which still means them."""
    for entry in _read().values():
        if entry.get("handle") == handle and entry.get("claimed") not in (None, handle):
            return entry["claimed"]
    return None
