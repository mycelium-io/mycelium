# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""
Identity management for Mycelium CLI.

Generates and manages handles for agent identification.
Format: DisplayName#session (e.g., "julvalen#a8f3")
"""

import secrets
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from mycelium.config import MyceliumConfig
    from mycelium_backend_client.models import WhoamiRead


def get_session_path() -> Path:
    return Path.cwd() / ".mycelium" / "session"


def load_session() -> str | None:
    session_path = get_session_path()
    if session_path.exists():
        return session_path.read_text().strip()
    return None


def save_session(session_id: str) -> None:
    session_path = get_session_path()
    session_path.parent.mkdir(parents=True, exist_ok=True)
    session_path.write_text(session_id)


def generate_session_id() -> str:
    return secrets.token_hex(2)


def generate_handle(name: str, session_id: str) -> str:
    return f"{name}#{session_id}"


def get_current_handle(config: "MyceliumConfig") -> str | None:
    """Get the current handle if identity is configured."""
    if not config.identity.name:
        return None

    session_id = load_session()
    if not session_id:
        return None

    return generate_handle(config.identity.name, session_id)


#: The old hardcoded default author. Kept so a script that still passes it
#: explicitly is treated as "unset" and resolves to the real caller, rather
#: than a placeholder a gated hub rejects.
LEGACY_ACTOR_SENTINEL = "cli-user"


#: Per-process cache of ``/api/whoami`` keyed by hub URL. One CLI invocation is
#: one process against one hub with one credential, so the answer is stable for
#: the run; without this, a command that asks "who am I" several times (a board
#: verb reads it per sub-call) would re-hit the hub each time.
_WHOAMI_CACHE: dict[str, "WhoamiRead | None"] = {}


def _hub_whoami(config: "MyceliumConfig") -> "WhoamiRead | None":
    """The hub's ``GET /api/whoami``, or None when the hub can't be reached.

    Called with whatever credential the CLI holds (or none). The hub derives the
    reported ``handle`` from the same claim it enforces ``created_by`` against, so
    a client never has to guess which claim a gated hub trusts. A 401 means the
    hub is gated and we presented no valid token, which is reported as
    ``{gated: True, handle: None}`` so the caller can tell "log in first" apart
    from "ungated, name yourself". Cached per hub for the process.
    """
    url = config.server.api_url
    if url in _WHOAMI_CACHE:
        return _WHOAMI_CACHE[url]

    from mycelium import client
    from mycelium_backend_client.api.auth import whoami_api_whoami_get
    from mycelium_backend_client.models import WhoamiRead

    result: WhoamiRead | None
    try:
        with client.typed_client(config, timeout=5.0, raise_on_unexpected_status=False) as http:
            resp = whoami_api_whoami_get.sync_detailed(client=http)
        if resp.status_code == 401:  # noqa: PLR2004
            result = WhoamiRead(gated=True, handle=None)
        else:
            result = resp.parsed if isinstance(resp.parsed, WhoamiRead) else None
    except Exception:
        result = None
    _WHOAMI_CACHE[url] = result
    return result


def resolve_actor(
    config: "MyceliumConfig",
    override: str | None = None,
    *,
    require: bool = True,
    fallback: str = LEGACY_ACTOR_SENTINEL,
) -> str:
    """The one seam every command uses to answer "who am I acting as".

    The order is ``caller.handle``'s: an explicit ``--as`` override,
    ``MYCELIUM_AGENT_HANDLE``, the agent herdr's registry maps this pane to,
    this folder's membership (``mycelium join``), the
    principal the hub resolves our token to (``/api/whoami``, exactly the value a
    gated hub enforces ``created_by`` against), the locally configured identity
    (``mycelium iam``), and last ``fallback`` (the ``cli-user`` sentinel for a
    write's author, ``"unknown"`` for a sender), so a zero-config local hub keeps
    working. The exception is a gated hub we're not signed in to, where
    ``require`` raises a clear "log in" error rather than stamping a placeholder
    the gate is guaranteed to reject.

    The ``cli-user`` sentinel is also treated as "unset" if passed as ``override``,
    so an old script resolves to the real caller.
    """
    from mycelium import caller

    answer = caller.handle(config, override)
    if answer.value:
        return answer.value
    who = _hub_whoami(config)
    if require and who and who.gated:
        import typer

        raise typer.BadParameter(
            "this hub is gated and you are not signed in, so there is no identity "
            "to attribute this to. Run `mycelium login`, or set one with "
            "`mycelium iam <handle>`, or pass `--as <handle>` explicitly."
        )
    return fallback


# ── for code: identity.set / identity.get ─────────────────────────────────────

#: Where :func:`get` says a handle came from when :func:`set` named it.
SET_IN_CODE = "identity.set"

#: The handle :func:`set` named for this process, if it did.
_set_handle: str | None = None


def set(handle: str, *, room: str | None = None) -> str:  # noqa: A001
    """Act as ``handle`` for the rest of this process, as ``MYCELIUM_AGENT_HANDLE`` does.

    Every :class:`mycelium.Room` made after it acts as ``handle``, unless it is
    given a ``handle=`` of its own. Child processes inherit it, so a
    ``mycelium`` command the code runs acts as ``handle`` too. It checks with
    the hub now rather than at the first write: that the hub can be reached,
    that this machine is signed in when the hub needs it, and that ``handle``
    is a member of the room (``room``, or the one a ``Room()`` would use).
    Pass ``room`` when the code works in a room by name: without it, this
    checks whatever room this machine or folder points at, and when none
    does, it checks only the hub and the sign-in. Whether the sign-in may act
    as ``handle`` is the hub's to say, at the first write.
    """
    import os

    from mycelium import caller
    from mycelium.agent_credentials import normalize_handle
    from mycelium.cli_options import resolve_room
    from mycelium.config import MyceliumConfig
    from mycelium.exceptions import MyceliumError

    global _set_handle  # noqa: PLW0603
    name = normalize_handle(handle)
    if not name:
        msg = "identity.set needs a handle, such as identity.set('builder')."
        raise ValueError(msg)
    config = MyceliumConfig.load()
    who = _hub_whoami(config)
    if who is None:
        msg = f"Can't reach the hub at {config.server.api_url}."
        raise MyceliumError(msg)
    if who.gated and not who.handle:
        msg = (
            "This hub needs a sign-in. Run `mycelium login` on this machine, or give "
            "the process its own with MYCELIUM_AGENT_AUTH_CLIENT_ID and "
            "MYCELIUM_AGENT_AUTH_CLIENT_SECRET."
        )
        raise MyceliumError(msg)
    try:
        room_name = resolve_room(config, room)
    except MyceliumError:
        room_name = None
    if room_name and name != who.handle and not _is_member(config, room_name, name):
        msg = f"@{name} isn't a member of {room_name}."
        raise MyceliumError(
            msg, suggestion=f"Add it with: mycelium agent create {name} --room {room_name}"
        )
    os.environ[caller.HANDLE_ENV] = name
    _set_handle = name
    return name


def get() -> "tuple[str | None, str]":
    """Who this process acts as, and where that answer came from.

    The same answer, from the same sources in the same order, as
    ``mycelium whoami --sources``: ``identity.set``, the environment, the herdr
    pane, this folder's membership, this machine's sign-in or ``mycelium iam``.
    ``(None, "default")`` when nothing says.
    """
    import os

    from mycelium import caller
    from mycelium.config import MyceliumConfig

    answer = caller.handle(MyceliumConfig.load())
    if (
        _set_handle
        and answer.value == _set_handle
        and os.environ.get(caller.HANDLE_ENV, "").strip() == _set_handle
    ):
        return answer.value, SET_IN_CODE
    return answer.value, answer.source


def _is_member(config: "MyceliumConfig", room: str, handle: str) -> bool:
    """Whether ``handle`` is an agent in ``room``, or a person the hub knows."""
    from mycelium import client
    from mycelium_backend_client.api.agents import list_agents_api_rooms_room_name_agents_get
    from mycelium_backend_client.api.users import get_user_api_users_handle_get

    with client.typed_client(config, timeout=10.0, raise_on_unexpected_status=False) as http:
        agents = list_agents_api_rooms_room_name_agents_get.sync(room, client=http)
        if isinstance(agents, list) and any(getattr(a, "handle", None) == handle for a in agents):
            return True
        found = get_user_api_users_handle_get.sync_detailed(handle, client=http)
    return found.status_code == 200  # noqa: PLR2004
