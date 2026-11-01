# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""Where a person's sign-in (``mycelium login``) is kept.

The normal flow, like ``gh``: ``mycelium login`` keeps the session, refresh
token included, and later commands renew it quietly when it runs out. It's
kept in the system keychain (the macOS Keychain, Windows Credential Manager,
the Secret Service on Linux), one entry per hub, rather than in a plain file.
Where there's no keychain to use (a server with no Secret Service), or the
keychain wouldn't keep it (a prompt declined, or an entry too large for
Windows to hold), it goes in a ``0600`` file, and ``mycelium login`` says
which.

A process reads the session from where it's kept once and keeps it in memory,
going back only when it needs renewing (another process may have renewed it
already). A keychain entry that asks before it's read, as one made by a
different ``mycelium`` does on macOS, then asks once a renewal rather than on
every call to the hub.

Inside an agent's pane the person's sign-in is never used or kept
(``caller.in_agent_pane``): an agent acts with its own credentials.

A file written before this is moved into the keychain the first time it's
read, and deleted. If the keychain refuses the move, that's remembered
(``keychain-refused.json``), so later commands don't ask again; the next
``mycelium login`` tries the keychain afresh.
"""

from __future__ import annotations

import json
import threading
from typing import TYPE_CHECKING, Any

from mycelium import caller
from mycelium.tokens import StoredToken, clear_token, load_token, save_token, token_path

if TYPE_CHECKING:
    from pathlib import Path

    from mycelium.config import MyceliumConfig

#: Where the session is kept: the system keychain, a file because there's no
#: keychain, or a file because the keychain wouldn't keep it.
KEYCHAIN, FILE, REFUSED = "keychain", "file", "refused"

#: The keychain service every Mycelium sign-in is kept under, one account per hub.
SERVICE = "Mycelium sign-in"

#: ``{hub: (session, where)}`` this process has read or written.
_SESSIONS: dict[str, tuple[StoredToken, str]] = {}
_lock = threading.Lock()


class InAgentPane(Exception):
    """Refused: a person's sign-in can't be used or kept from an agent's pane."""


def _hub(config: MyceliumConfig) -> str:
    return config.server.api_url.rstrip("/")


def _keyring() -> Any:
    """The system keychain, or ``None`` where there's none to use."""
    try:
        import keyring
        from keyring.backends import fail
    except ImportError:
        return None
    try:
        backend = keyring.get_keyring()
    except Exception:  # noqa: BLE001 - a broken backend is no keychain
        return None
    if isinstance(backend, fail.Keyring) or getattr(backend, "priority", 1) <= 0:
        return None
    return keyring


def _keychain_get(hub: str) -> StoredToken | None:
    kr = _keyring()
    if kr is None:
        return None
    try:
        raw = kr.get_password(SERVICE, hub)
    except Exception:  # noqa: BLE001 - locked or unavailable: nothing kept there
        return None
    if not raw:
        return None
    try:
        data = json.loads(raw)
    except ValueError:
        return None
    return StoredToken.from_dict(data) if isinstance(data, dict) else None


def _keychain_set(hub: str, token: StoredToken) -> str:
    """Keep ``token`` in the keychain: :data:`KEYCHAIN` when it took it,
    :data:`FILE` when there's no keychain, :data:`REFUSED` when it wouldn't."""
    kr = _keyring()
    if kr is None:
        return FILE
    try:
        kr.set_password(SERVICE, hub, json.dumps(token.to_dict()))
    except Exception:  # noqa: BLE001 - a declined prompt, or an entry too large for it
        return REFUSED
    return KEYCHAIN


def _keychain_delete(hub: str) -> bool:
    kr = _keyring()
    if kr is None:
        return False
    try:
        kr.delete_password(SERVICE, hub)
    except Exception:  # noqa: BLE001 - nothing there to delete
        return False
    return True


def _refused_path() -> Path:
    """Where the hubs whose keychain move was refused are remembered."""
    return token_path().with_name("keychain-refused.json")


def _refused() -> set[str]:
    try:
        data = json.loads(_refused_path().read_text())
    except (OSError, ValueError):
        return set()
    return {str(h) for h in data} if isinstance(data, list) else set()


def _set_refused(hub: str, *, refused: bool) -> None:
    hubs = _refused()
    if (hub in hubs) == refused:
        return
    hubs = hubs | {hub} if refused else hubs - {hub}
    path = _refused_path()
    try:
        if hubs:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(sorted(hubs)) + "\n")
        else:
            path.unlink(missing_ok=True)
    except OSError:
        pass  # remembered for this process only, then


def _read(hub: str) -> tuple[StoredToken | None, str | None]:
    """The session from where it's kept, moving a file into the keychain unless
    the keychain refused that before."""
    if (kept := _keychain_get(hub)) is not None:
        return kept, KEYCHAIN
    stored = load_token()
    if stored is None:
        return None, None
    if hub in _refused():
        return stored, REFUSED
    # A file from before the keychain: move it in, then remove the file.
    moved = _keychain_set(hub, stored)
    if moved == KEYCHAIN:
        clear_token()
        return stored, KEYCHAIN
    if moved == REFUSED:
        _set_refused(hub, refused=True)
    return stored, moved


def load(config: MyceliumConfig, *, fresh: bool = False) -> tuple[StoredToken | None, str | None]:
    """The person's session for this hub and where it's kept; ``(None, None)``
    when there is none, or when this is an agent's pane.

    From memory once this process has read it; ``fresh`` reads where it's kept
    again, which a renewal does first, since another process may have renewed
    it already. No session isn't remembered, so a ``mycelium login`` in another
    terminal is seen at once."""
    if caller.in_agent_pane():
        return None, None
    hub = _hub(config)
    with _lock:
        if not fresh and hub in _SESSIONS:
            return _SESSIONS[hub]
        stored, where = _read(hub)
        if stored is not None and where is not None:
            _SESSIONS[hub] = (stored, where)
        else:
            _SESSIONS.pop(hub, None)
        return stored, where


def save(config: MyceliumConfig, token: StoredToken) -> str:
    """Keep ``token`` for this hub: in the keychain, else in a ``0600`` file.
    Returns where (:data:`KEYCHAIN`, :data:`FILE` or :data:`REFUSED`)."""
    if caller.in_agent_pane():
        msg = "an agent's pane can't keep a person's sign-in"
        raise InAgentPane(msg)
    hub = _hub(config)
    where = _keychain_set(hub, token)
    # A login tries the keychain afresh: what it says now is what's remembered.
    _set_refused(hub, refused=where == REFUSED)
    if where == KEYCHAIN:
        clear_token()
    else:
        save_token(token)
    with _lock:
        _SESSIONS[hub] = (token, where)
    return where


def renewed(config: MyceliumConfig, token: StoredToken, where: str | None) -> None:
    """Keep a session the CLI just renewed where the old one was."""
    hub = _hub(config)
    if where == KEYCHAIN and _keychain_set(hub, token) == KEYCHAIN:
        kept = KEYCHAIN
    else:
        save_token(token)
        kept = where if where in (FILE, REFUSED) else FILE
    with _lock:
        _SESSIONS[hub] = (token, kept)


def clear(config: MyceliumConfig) -> bool:
    """Forget the session for this hub, wherever it was kept."""
    hub = _hub(config)
    with _lock:
        _SESSIONS.pop(hub, None)
    from_keychain = _keychain_delete(hub)
    from_file = clear_token()
    return from_keychain or from_file


def where_described(where: str | None) -> str:
    """Where a sign-in is kept, as `mycelium login` says it."""
    if where == KEYCHAIN:
        return "the system keychain"
    return str(token_path())
