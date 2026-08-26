# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""
Token cache for the CLI's OIDC session (``mycelium login``).

Tokens are secrets, so they deliberately do **not** live in ``config.toml``:
that file is routinely printed, copied between machines, and mirrored into
``config.json`` for JS consumers. The session lands in its own file,
``~/.mycelium/token.json``, created ``0600`` so it is readable only by its owner.

The CLI reads a token's claims but never *verifies* them; verification is the
hub's job (``app/services/auth.py`` validates the signature against the issuer's
JWKS). Claims are decoded here only to show who you are logged in as and when the
session expires; nothing the CLI decides on their basis grants access to
anything.
"""

from __future__ import annotations

import base64
import binascii
import json
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

#: Treat a token as expired this many seconds before its ``exp``, so a request
#: can't be issued with a token that dies in flight.
DEFAULT_LEEWAY_S = 60.0

#: Overrides the cache location (tests, and CI runners with a shared home).
TOKEN_FILE_ENV = "MYCELIUM_TOKEN_FILE"


def format_span(seconds: float) -> str:
    """A span at the precision a human reads it at, not a countdown.

    Rounded rather than floored: a token minted seconds ago with a 5-minute
    lifetime has 299.9s left, and reporting that as "4 min" makes the issuer's
    setting look like something else.
    """
    minutes = round(seconds / 60)
    if minutes < 1:
        return "under a minute"
    if minutes < 90:  # noqa: PLR2004 — an hour and a half still reads better in minutes
        return f"{minutes} min"
    hours = round(minutes / 60)
    if hours < 48:  # noqa: PLR2004 — two days is where days start reading better
        return f"{hours} hours"
    return f"{round(hours / 24)} days"


def token_path() -> Path:
    """Where the session is cached (``~/.mycelium/token.json`` by default)."""
    override = os.environ.get(TOKEN_FILE_ENV, "").strip()
    if override:
        return Path(override).expanduser()

    from mycelium.config import MyceliumConfig

    return MyceliumConfig.get_global_config_dir() / "token.json"


def decode_claims(jwt: str) -> dict[str, Any]:
    """Decode a JWT's payload **without verifying it**.

    Returns ``{}`` for anything that isn't a readable JWT; an opaque access
    token is a legitimate thing for an issuer to hand out, and the CLI treats it
    as "a token I can't read claims from", not as an error.
    """
    parts = jwt.split(".")
    if len(parts) < 2:
        return {}
    payload = parts[1]
    padding = "=" * (-len(payload) % 4)
    try:
        raw = base64.urlsafe_b64decode(payload + padding)
        claims = json.loads(raw)
    except (ValueError, binascii.Error, UnicodeDecodeError):
        return {}
    return claims if isinstance(claims, dict) else {}


@dataclass(frozen=True)
class StoredToken:
    """A cached OIDC session: the access token plus what it takes to renew it."""

    access_token: str
    issuer: str
    client_id: str
    refresh_token: str | None = None
    #: Absolute epoch seconds, not a duration: a cached ``expires_in`` would
    #: silently mean something different every time the file is read.
    expires_at: float | None = None
    #: When renewal itself runs out, so a session can say when a re-login is
    #: actually due. ``None`` when the issuer reports no ``refresh_expires_in``,
    #: which is most of them — the refresh token is opaque, so there is nothing
    #: to read it off when it isn't volunteered.
    refresh_expires_at: float | None = None
    token_endpoint: str | None = None
    scope: str | None = None

    @property
    def claims(self) -> dict[str, Any]:
        """The access token's unverified claims (``{}`` if it isn't a JWT)."""
        return decode_claims(self.access_token)

    def handle(self, claim: str = "sub") -> str | None:
        """The ``@handle`` this token asserts, per the configured claim."""
        value = self.claims.get(claim)
        if not isinstance(value, str) or not value.strip():
            return None
        return value.strip().lstrip("@").lower()

    def expires_in(self, *, now: float | None = None) -> float | None:
        """Seconds until expiry, or ``None`` when the issuer gave no expiry."""
        if self.expires_at is None:
            return None
        return self.expires_at - (time.time() if now is None else now)

    def refresh_expires_in(self, *, now: float | None = None) -> float | None:
        """Seconds until renewal stops working, or ``None`` when unknown.

        Unknown is the common case and reads as "no deadline to report", not as
        "renewal never expires": an issuer that says nothing has said nothing.
        """
        if self.refresh_expires_at is None:
            return None
        return self.refresh_expires_at - (time.time() if now is None else now)

    def is_expired(self, *, leeway_s: float = DEFAULT_LEEWAY_S) -> bool:
        remaining = self.expires_in()
        return remaining is not None and remaining <= leeway_s

    def to_dict(self) -> dict[str, Any]:
        return {
            "access_token": self.access_token,
            "refresh_token": self.refresh_token,
            "expires_at": self.expires_at,
            "refresh_expires_at": self.refresh_expires_at,
            "issuer": self.issuer,
            "client_id": self.client_id,
            "token_endpoint": self.token_endpoint,
            "scope": self.scope,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> StoredToken | None:
        """Rehydrate a cache entry, or ``None`` if it isn't usable."""
        access_token = data.get("access_token")
        if not isinstance(access_token, str) or not access_token:
            return None
        expires_at = data.get("expires_at")
        refresh_expires_at = data.get("refresh_expires_at")
        return cls(
            access_token=access_token,
            issuer=str(data.get("issuer") or ""),
            client_id=str(data.get("client_id") or ""),
            refresh_token=data.get("refresh_token") or None,
            expires_at=float(expires_at) if isinstance(expires_at, int | float) else None,
            refresh_expires_at=(
                float(refresh_expires_at) if isinstance(refresh_expires_at, int | float) else None
            ),
            token_endpoint=data.get("token_endpoint") or None,
            scope=data.get("scope") or None,
        )


def load_token(path: Path | None = None) -> StoredToken | None:
    """The cached session, or ``None`` when logged out.

    A corrupt cache reads as logged out rather than raising: every command in the
    CLI consults this, and none of them should die because a token file got
    truncated.

    ``path`` selects a cache other than the human session's: an agent's minted
    token lives in its own file (``mycelium.agent_credentials``).
    """
    path = path or token_path()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    return StoredToken.from_dict(data)


def save_token(token: StoredToken, path: Path | None = None) -> Path:
    """Write the session to the cache, owner-readable only."""
    path = path or token_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    # os.open with 0600 rather than write_text + chmod: the file must never
    # exist, even momentarily, with the default mode.
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        json.dump(token.to_dict(), fh, indent=2)
        fh.write("\n")
    # An older cache may predate this mode; re-assert it on every write.
    os.chmod(path, 0o600)
    return path


def clear_token(path: Path | None = None) -> bool:
    """Delete the cached session. Returns whether there was one."""
    path = path or token_path()
    try:
        path.unlink()
    except FileNotFoundError:
        return False
    except OSError:
        return False
    return True
