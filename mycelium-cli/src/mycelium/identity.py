# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""
Identity management for Mycelium CLI.

Generates and manages handles for agent identification.
Format: DisplayName#session (e.g., "julvalen#a8f3")
"""

import os
import secrets
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from mycelium.config import MyceliumConfig


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


#: The old hardcoded default author. Kept only so a script that still passes it
#: explicitly is treated as "unset" and resolves to the real caller, rather than
#: a placeholder a gated hub rejects. Every write command used to default to it.
LEGACY_ACTOR_SENTINEL = "cli-user"


#: Per-process cache of ``/api/whoami`` keyed by hub URL. One CLI invocation is
#: one process against one hub with one credential, so the answer is stable for
#: the run; without this, a command that asks "who am I" several times (a board
#: verb reads it per sub-call) would re-hit the hub each time.
_WHOAMI_CACHE: dict[str, dict | None] = {}


def _hub_whoami(config: "MyceliumConfig") -> dict | None:
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

    result: dict | None
    try:
        with client.hub_client(config, timeout=5.0) as http:
            resp = http.get("/api/whoami")
        if resp.status_code == 401:
            result = {"gated": True, "handle": None}
        elif resp.status_code != 200:
            result = None
        else:
            result = resp.json()
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

    Precedence:

    1. an explicit ``--as`` override (acting-as, when the hub authorizes it),
    2. ``MYCELIUM_AGENT_HANDLE`` — the identity a resident runtime declares for
       itself (set by an adapter or the remote-agent bootstrap),
    3. the principal the hub resolves our token to (``/api/whoami``) — exactly the
       value a gated hub enforces ``created_by`` against,
    4. the locally-configured identity (``mycelium iam``), for an ungated hub,
    5. ``fallback`` (the ``cli-user`` sentinel for a write's author, ``"unknown"``
       for a sender), so a zero-config local hub keeps working — *unless* the hub
       is gated and we're not signed in, where ``require`` raises a clear "log in"
       error rather than stamping a placeholder the gate is guaranteed to reject.

    The ``cli-user`` sentinel is also treated as "unset" if passed as ``override``,
    so an old script resolves to the real caller.
    """
    if override and override != LEGACY_ACTOR_SENTINEL:
        return override
    env_handle = os.environ.get("MYCELIUM_AGENT_HANDLE", "").strip()
    if env_handle:
        return env_handle
    who = _hub_whoami(config)
    if who and who.get("handle"):
        return who["handle"]
    local = get_current_handle(config) or config.identity.name
    if local:
        return local
    if require and who and who.get("gated"):
        import typer

        raise typer.BadParameter(
            "this hub is gated and you are not signed in, so there is no identity "
            "to attribute this to. Run `mycelium login`, or set one with "
            "`mycelium iam <handle>`, or pass `--as <handle>` explicitly."
        )
    return fallback
