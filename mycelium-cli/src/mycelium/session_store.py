# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""Where a person's sign-in (``mycelium login``) is kept.

The normal flow, like ``gh``: ``mycelium login`` keeps the session, refresh
token included, and later commands renew it quietly when it runs out. It's
kept in the system keychain (the macOS Keychain, Windows Credential Manager,
the Secret Service on Linux), one entry per hub, rather than in a plain file.
Where there's no keychain to use (a server with no Secret Service, or an entry
too large for Windows to hold), it goes in a ``0600`` file, and ``mycelium
login`` says so.

Inside an agent's pane the person's sign-in is never used or kept
(``caller.in_agent_pane``): an agent acts with its own credentials.

A file written before this is moved into the keychain the first time it's
read, and deleted.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

from mycelium import caller
from mycelium.tokens import StoredToken, clear_token, load_token, save_token, token_path

if TYPE_CHECKING:
    from mycelium.config import MyceliumConfig

#: Where the session is kept: the system keychain, or a file.
KEYCHAIN, FILE = "keychain", "file"

#: The keychain service every Mycelium sign-in is kept under, one account per hub.
SERVICE = "Mycelium sign-in"


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


def _keychain_set(hub: str, token: StoredToken) -> bool:
    kr = _keyring()
    if kr is None:
        return False
    try:
        kr.set_password(SERVICE, hub, json.dumps(token.to_dict()))
    except Exception:  # noqa: BLE001 - no keychain, or the entry is too large for it
        return False
    return True


def _keychain_delete(hub: str) -> bool:
    kr = _keyring()
    if kr is None:
        return False
    try:
        kr.delete_password(SERVICE, hub)
    except Exception:  # noqa: BLE001 - nothing there to delete
        return False
    return True


def load(config: MyceliumConfig) -> tuple[StoredToken | None, str | None]:
    """The person's session for this hub and where it's kept; ``(None, None)``
    when there is none, or when this is an agent's pane."""
    if caller.in_agent_pane():
        return None, None
    hub = _hub(config)
    if (kept := _keychain_get(hub)) is not None:
        return kept, KEYCHAIN
    stored = load_token()
    if stored is None:
        return None, None
    # A file from before the keychain: move it in, then remove the file.
    if _keychain_set(hub, stored):
        clear_token()
        return stored, KEYCHAIN
    return stored, FILE


def save(config: MyceliumConfig, token: StoredToken) -> str:
    """Keep ``token`` for this hub: in the keychain, else in a ``0600`` file.
    Returns where (:data:`KEYCHAIN` or :data:`FILE`)."""
    if caller.in_agent_pane():
        msg = "an agent's pane can't keep a person's sign-in"
        raise InAgentPane(msg)
    if _keychain_set(_hub(config), token):
        clear_token()
        return KEYCHAIN
    save_token(token)
    return FILE


def renewed(config: MyceliumConfig, token: StoredToken, where: str | None) -> None:
    """Keep a session the CLI just renewed where the old one was."""
    if where == KEYCHAIN and _keychain_set(_hub(config), token):
        return
    save_token(token)


def clear(config: MyceliumConfig) -> bool:
    """Forget the session for this hub, wherever it was kept."""
    from_keychain = _keychain_delete(_hub(config))
    from_file = clear_token()
    return from_keychain or from_file


def where_described(where: str | None) -> str:
    """Where a sign-in is kept, as `mycelium login` says it."""
    if where == KEYCHAIN:
        return "the system keychain"
    return str(token_path())
