# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""Changing the hub's settings from the app's Hub page.

The settings live in ``config.toml`` on the hub's machine. The hub never edits
that file itself: it runs the CLI's own ``mycelium config set <key> -`` with the
value on stdin, so a change goes through the one path that validates it and
that ``config apply`` renders from (CLAUDE.md, "A config field that reaches no
container is a bug"). The keys the page may change, and how each is edited,
are frozen in ``contracts/hub-settings.json``.

Who may change them:

- **A desktop hub**, which listens on 127.0.0.1 only, so whoever reaches it is
  on this machine. The supervisor that started it says where the CLI is
  (``MYCELIUM_CONFIG_CLI``). An agent on the same computer with no token
  counts as the person here; it could already run ``mycelium config set`` in
  its own shell, so this gives it nothing new. A web page the person visits
  is refused (``foreign_page``).
- **A person**, when sign-in is on. The hub has no admin role (a token is a
  ``user`` or an ``agent``), so a person's token is the line; an agent's is
  refused.

Anything else is read-only, and the page says why: a hub in Docker has no CLI
beside it and its ``config.toml`` on the host, out of reach.

Every setting here is read when the hub starts, so a change takes effect at the
next start. The desktop supervisor restarts the hub on request: the hub writes
``restart_marker`` in its data folder and shuts down, and the supervisor sees
the marker and starts it again at once with ``config.toml`` read afresh.
"""

from __future__ import annotations

import json
import os
import signal
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from fastapi import Request

from app.config import settings
from app.services import actor

#: The editable keys, as ``contracts/hub-settings.json`` freezes them (asserted
#: by ``tests/test_hub_config.py``). The image carries only this package, so
#: this is a checked copy.
EDITABLE: dict[str, dict[str, Any]] = {
    "llm.model": {"type": "text"},
    "llm.base_url": {"type": "text"},
    "llm.api_key": {"type": "secret"},
    "verifier.enabled": {"type": "bool"},
    "voice.enabled": {"type": "bool", "app_owned": True},
    "voice.model": {"type": "choice", "choices": ["fast", "accurate"], "app_owned": True},
    "voice.speech_url": {"type": "text"},
    "voice.speech_model": {"type": "text"},
    "voice.speech_voice": {"type": "text"},
    "voice.speech_api_key": {"type": "secret"},
    "telemetry.send_product_analytics": {"type": "bool", "app_owned": True},
    "worker.tools": {"type": "bool"},
    "worker.pi_timeout_s": {"type": "number"},
    "worker.max_turns_per_room": {"type": "int"},
    "board.dependency_gate": {"type": "bool"},
}
RESTART_MARKER = ".hub-restart-requested"

#: How long one ``config set`` may take before the write is reported failed.
CLI_TIMEOUT_S = 30

#: What was saved since this hub started, by key, which takes effect at the
#: next start; None for a cleared text or key.
_changed: dict[str, Any] = {}


class HubConfigError(ValueError):
    """A change the hub refuses, with the reason the page shows."""

    def __init__(self, detail: str, status: int = 422) -> None:
        super().__init__(detail)
        self.detail = detail
        self.status = status


@dataclass(frozen=True)
class Access:
    """Whether this caller may change the hub's settings, and why not."""

    may_edit: bool
    reason: str | None
    #: The hub can restart itself (a desktop hub, whose supervisor starts it again).
    can_restart: bool
    #: Keys the desktop app sets itself, edited in the app's own settings.
    app_owned: list[str]


def desktop() -> bool:
    return os.environ.get("MYCELIUM_HUB_MODE", "").strip() == "desktop"


def cli() -> list[str] | None:
    """The CLI to run ``config set`` with, as the supervisor named it; None without one."""
    raw = os.environ.get("MYCELIUM_CONFIG_CLI", "").strip()
    if not raw:
        return None
    try:
        argv = json.loads(raw)
    except json.JSONDecodeError:
        argv = [raw]
    if not isinstance(argv, list) or not argv or not all(isinstance(a, str) for a in argv):
        return None
    return argv


def access(request: Request | None) -> Access:
    app_owned = [k for k, spec in EDITABLE.items() if spec.get("app_owned")] if desktop() else []
    principal = actor.current_principal(request)
    if cli() is None:
        return Access(
            False,
            "This hub can't reach its config.toml (it runs in Docker or another machine). "
            "Change it on the hub's machine with mycelium config set.",
            False,
            app_owned,
        )
    if principal is not None and principal.role != "user":
        return Access(False, "Only a person can change the hub's settings.", desktop(), app_owned)
    if principal is None and not desktop():
        return Access(
            False,
            "Turn on sign-in to change this hub from the app, so only people can.",
            False,
            app_owned,
        )
    return Access(True, None, desktop(), app_owned)


#: The names this computer goes by, for a desktop hub's own requests.
LOOPBACK = frozenset({"127.0.0.1", "localhost", "::1"})


def foreign_page(request: Request) -> str | None:
    """Why a change to a desktop hub didn't come from this computer, or None.

    A desktop hub trusts whoever reaches it because it listens on 127.0.0.1
    alone. A web page the person visits can still reach it by DNS rebinding:
    its own domain made to resolve to 127.0.0.1, so the browser treats the hub
    as the page's own origin. Such a request names that domain in ``Host``
    when it goes to the hub directly, and in ``Origin`` when it goes through
    the app's UI, whose proxy sends the hub's own address as ``Host``. Saving
    a setting and restarting are refused unless both say this computer (or an
    origin the hub was set up to allow).
    """
    if not desktop():
        return None
    host = urlsplit(f"//{request.headers.get('host', '')}")
    server = request.scope.get("server")
    port = server[1] if server else None
    if host.hostname not in LOOPBACK or (port and host.port and host.port != port):
        return "This change has to come from Mycelium on this computer."
    origin = request.headers.get("origin")
    if origin is not None and origin not in settings.CORS_ORIGINS:
        parts = urlsplit(origin)
        if parts.scheme not in ("http", "https") or parts.hostname not in LOOPBACK:
            return "This change has to come from Mycelium on this computer."
    return None


def _coerce(key: str, value: Any) -> str | None:
    """The value as ``config set`` takes it (JSON for a bool or a number), or None
    to clear a text or secret setting."""
    kind = EDITABLE[key]["type"]
    if kind == "bool":
        if not isinstance(value, bool):
            raise HubConfigError(f"{key} is on or off")
        return "true" if value else "false"
    if kind in ("int", "number"):
        if isinstance(value, bool) or not isinstance(value, int | float):
            raise HubConfigError(f"{key} is a number")
        if kind == "int" and int(value) != value:
            raise HubConfigError(f"{key} is a whole number")
        if value <= 0:
            raise HubConfigError(f"{key} is more than 0")
        return str(int(value)) if kind == "int" else str(float(value))
    if kind == "choice":
        if value not in EDITABLE[key]["choices"]:
            raise HubConfigError(f"{key} is one of {', '.join(EDITABLE[key]['choices'])}")
        return str(value)
    # text and secret
    if value is None or (isinstance(value, str) and not value.strip()):
        return None
    if not isinstance(value, str):
        raise HubConfigError(f"{key} is text")
    return value.strip()


def _run(argv: list[str], stdin: str) -> None:
    try:
        # argv is the supervisor's own CLI and a fixed verb; the value goes on stdin.
        done = subprocess.run(
            argv,
            input=stdin,
            capture_output=True,
            text=True,
            timeout=CLI_TIMEOUT_S,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as err:
        raise HubConfigError(f"Couldn't run the CLI to save it: {err}", status=500) from err
    if done.returncode != 0:
        said = (done.stderr or done.stdout or "").strip().splitlines()
        raise HubConfigError(said[-1] if said else "The CLI refused the change", status=422)


def write(changes: dict[str, Any], app_owned: list[str]) -> list[str]:
    """Save each change to config.toml through the CLI; returns the keys saved.

    Every change is checked before any is written, so a bad one saves nothing.
    """
    base = cli()
    if base is None:
        raise HubConfigError("This hub can't reach its config.toml.", status=409)
    unknown = [k for k in changes if k not in EDITABLE]
    if unknown:
        raise HubConfigError(f"Not a setting the app can change: {', '.join(sorted(unknown))}")
    owned = [k for k in changes if k in app_owned]
    if owned:
        raise HubConfigError(
            f"{', '.join(sorted(owned))} is set in the app's own settings, which win over config.toml"
        )
    values = {key: _coerce(key, value) for key, value in changes.items()}
    for key, value in values.items():
        # A cleared text or key is written empty, which config set reads as unset.
        _run([*base, "config", "set", key, "-"], "" if value is None else value)
        # Kept as the page shows it: a key only as set or not, never the key.
        kind = EDITABLE[key]["type"]
        if kind == "secret":
            _changed[key] = value is not None
        elif kind == "text":
            _changed[key] = value or ""
        else:
            _changed[key] = changes[key]
    return list(values)


def pending() -> list[str]:
    """Keys saved since this hub started: they apply at the next start."""
    return sorted(_changed)


def saved() -> dict[str, Any]:
    """What each key was saved as since this hub started, so the page shows
    config.toml's value rather than the one the hub is still running with."""
    return dict(_changed)


def request_restart() -> None:
    """Ask the supervisor to start this hub again, then shut down gracefully."""
    marker = Path(settings.MYCELIUM_DATA_DIR).expanduser() / RESTART_MARKER
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text("restart\n", encoding="utf-8")
    os.kill(os.getpid(), signal.SIGINT)


def reset() -> None:
    """Forget pending changes (tests)."""
    _changed.clear()
