# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""
Per-agent credentials — an agent's *own* token, resolved at the one client seam.

A human runs ``mycelium login`` and gets a session. An agent can't: there is no
browser to open, no consent screen to click, and nobody sitting there to do it.
So an agent authenticates as a **workload**: its own OIDC client, minted with the
``client_credentials`` grant, whose ``sub`` is the client id — which is the
agent's handle, the same handle the hub binds its writes to
(``app/services/actor.py``). Two agents on one machine therefore hold two
different credentials, and revoking one client leaves the other untouched.

Three sources, most specific first:

* **A pre-minted token** (``MYCELIUM_AGENT_AUTH_TOKEN``). The seam for a
  credential this CLI didn't obtain — a token from CI, or a JWT-SVID a SPIRE
  sidecar wrote out. Nothing here mints or renews it; the writer owns its
  lifetime.
* **The environment** (``MYCELIUM_AGENT_AUTH_CLIENT_ID`` / ``…_CLIENT_SECRET``),
  for a container that runs exactly one agent and has no config file.
* **The credential store**, ``~/.mycelium/agent-credentials.json``, written by
  ``mycelium agent credential set``. A secret, so it is ``0600`` and lives
  outside ``config.toml`` — the same reason the human session does
  (``mycelium.tokens``).

The issuer itself is not a secret and is shared by every agent on the machine,
so it comes from ``[agent_auth]`` in config (or ``MYCELIUM_AGENT_AUTH_ISSUER``).

**Off by default, and silent when it can't help.** No credential configured
means no token, which is exactly today's behavior against an ungated hub. A mint
that fails degrades to *no header* rather than to an error: against an ungated
hub the call still works, and against a gated one the 401 is the truthful
answer.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, replace
from pathlib import Path
from typing import TYPE_CHECKING, Any

from rich.console import Console

if TYPE_CHECKING:
    from mycelium.config import MyceliumConfig

#: Overrides the credential store location (tests, CI runners with a shared home).
CREDENTIAL_STORE_ENV = "MYCELIUM_AGENT_CREDENTIALS_FILE"

#: The handle a resident runtime is running as, when the caller doesn't name one.
#: Already the attribution signal for a resident session, and the credential
#: follows the identity rather than being a second, separately-set thing.
AGENT_HANDLE_ENV = "MYCELIUM_AGENT_HANDLE"

STATIC_TOKEN_ENV = "MYCELIUM_AGENT_AUTH_TOKEN"
CLIENT_ID_ENV = "MYCELIUM_AGENT_AUTH_CLIENT_ID"
CLIENT_SECRET_ENV = "MYCELIUM_AGENT_AUTH_CLIENT_SECRET"

_stderr = Console(stderr=True)

#: One warning per handle per process — every command builds several clients and
#: each would otherwise repeat the same failure.
_warned: set[str] = set()

#: Handles are lowercase slugs, but the cache path is derived from caller input,
#: so anything outside the slug alphabet is folded away before it reaches a path.
_UNSAFE = re.compile(r"[^a-z0-9._-]+")


def normalize_handle(raw: str | None) -> str | None:
    """The canonical handle a credential is keyed by.

    Matches the backend's ``auth.normalize_handle``, and drops a session
    qualifier (``alpha#a8f3``): a session is the same agent, so it presents the
    same credential.
    """
    if not isinstance(raw, str):
        return None
    base = raw.partition("#")[0]
    return base.strip().lstrip("@").lower() or None


def ambient_handle() -> str | None:
    """The handle this process is running as, when it says so."""
    return normalize_handle(os.environ.get(AGENT_HANDLE_ENV))


def store_path() -> Path:
    """Where per-agent credentials are kept (``~/.mycelium/agent-credentials.json``)."""
    override = os.environ.get(CREDENTIAL_STORE_ENV, "").strip()
    if override:
        return Path(override).expanduser()

    from mycelium.config import MyceliumConfig

    return MyceliumConfig.get_global_config_dir() / "agent-credentials.json"


def token_cache_path(handle: str) -> Path:
    """Where an agent's *minted* token is cached, one file per agent."""
    safe = _UNSAFE.sub("-", handle) or "agent"
    return store_path().parent / "agent-tokens" / f"{safe}.json"


@dataclass(frozen=True)
class AgentCredential:
    """How one agent proves who it is."""

    handle: str
    client_id: str
    client_secret: str | None = None
    issuer: str | None = None
    scopes: str | None = None
    audience: str | None = None
    #: A token obtained elsewhere (CI, a SPIRE sidecar). Used as-is, never minted.
    token: str | None = None

    def redacted(self) -> dict[str, Any]:
        """What this credential is, with nothing secret in it."""
        return {
            "handle": self.handle,
            "client_id": self.client_id,
            "issuer": self.issuer,
            "scopes": self.scopes,
            "audience": self.audience,
            "has_secret": bool(self.client_secret),
            "static_token": bool(self.token),
        }


def _read_store() -> dict[str, dict[str, Any]]:
    """The stored per-agent entries. A damaged store reads as empty, not as an error."""
    try:
        data = json.loads(store_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if not isinstance(data, dict):
        return {}
    agents = data.get("agents")
    if not isinstance(agents, dict):
        return {}
    return {k: v for k, v in agents.items() if isinstance(v, dict)}


def _write_store(agents: dict[str, dict[str, Any]]) -> Path:
    """Persist the store owner-readable only — it holds client secrets."""
    path = store_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    # os.open with 0600 rather than write_text + chmod: the file must never exist,
    # even momentarily, with the default mode.
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        json.dump({"agents": agents}, fh, indent=2, sort_keys=True)
        fh.write("\n")
    # An older store may predate this mode; re-assert it on every write.
    os.chmod(path, 0o600)
    return path


def save_credential(
    handle: str,
    *,
    client_id: str | None = None,
    client_secret: str | None = None,
    issuer: str | None = None,
    scopes: str | None = None,
    audience: str | None = None,
) -> Path:
    """Record an agent's credential, replacing any entry it already had."""
    key = normalize_handle(handle) or handle
    agents = _read_store()
    agents[key] = {
        "client_id": client_id or key,
        "client_secret": client_secret,
        "issuer": issuer.rstrip("/") if issuer else None,
        "scopes": scopes,
        "audience": audience,
    }
    path = _write_store(agents)
    # A stale minted token belongs to the credential that just got replaced.
    clear_cached_token(key)
    return path


def remove_credential(handle: str) -> bool:
    """Forget an agent's credential. Returns whether there was one."""
    key = normalize_handle(handle) or handle
    agents = _read_store()
    if key not in agents:
        return False
    del agents[key]
    _write_store(agents)
    clear_cached_token(key)
    return True


def list_credentials() -> dict[str, AgentCredential]:
    """Every stored credential, keyed by handle."""
    return {
        handle: AgentCredential(
            handle=handle,
            client_id=str(entry.get("client_id") or handle),
            client_secret=entry.get("client_secret") or None,
            issuer=entry.get("issuer") or None,
            scopes=entry.get("scopes") or None,
            audience=entry.get("audience") or None,
        )
        for handle, entry in _read_store().items()
    }


def resolve(config: MyceliumConfig, handle: str | None = None) -> AgentCredential | None:
    """The credential an agent should present, or ``None`` when it has none.

    ``None`` is the default and the common case: no agent credential configured,
    so the caller attaches nothing and behaves as it always has.
    """
    resolved_handle = normalize_handle(handle) or ambient_handle()
    if resolved_handle is None:
        return None

    stored = list_credentials().get(resolved_handle)
    env_token = os.environ.get(STATIC_TOKEN_ENV, "").strip() or None
    env_client_id = os.environ.get(CLIENT_ID_ENV, "").strip() or None
    env_secret = os.environ.get(CLIENT_SECRET_ENV, "").strip() or None

    # A shared issuer is configuration, not a credential: on its own it must not
    # turn every handle into a token request. Something has to have been issued
    # *to this agent* first.
    if stored is None and not (env_token or env_client_id or env_secret):
        return None

    base = stored or AgentCredential(handle=resolved_handle, client_id=resolved_handle)
    return replace(
        base,
        client_id=env_client_id or base.client_id,
        client_secret=env_secret or base.client_secret,
        issuer=base.issuer or config.agent_auth.issuer,
        scopes=base.scopes or config.agent_auth.scopes,
        audience=base.audience or config.agent_auth.audience,
        token=env_token,
    )


def _warn_once(handle: str, message: str) -> None:
    if handle in _warned:
        return
    _warned.add(handle)
    _stderr.print(message)


def _cached_token(handle: str, credential: AgentCredential) -> str | None:
    """A cached mint that is still usable *and* still belongs to this credential."""
    from mycelium.tokens import load_token

    cached = load_token(token_cache_path(handle))
    if cached is None or cached.is_expired():
        return None
    # A credential re-pointed at a different client or issuer must not keep
    # presenting the token the old one minted.
    if cached.client_id != credential.client_id:
        return None
    if credential.issuer and cached.issuer and cached.issuer != credential.issuer:
        return None
    return cached.access_token


def clear_cached_token(handle: str) -> bool:
    """Drop an agent's cached mint. Returns whether there was one."""
    from mycelium.tokens import clear_token

    return clear_token(token_cache_path(handle))


def _mint(handle: str, credential: AgentCredential) -> str | None:
    """Obtain a fresh token for the credential, caching it. ``None`` if it can't."""
    from mycelium import oidc
    from mycelium.tokens import StoredToken, save_token

    if not credential.issuer:
        _warn_once(
            handle,
            f"[yellow]@{handle} has a credential but no issuer to mint it from.[/yellow] "
            "[dim]Set one with 'mycelium config set agent_auth.issuer <url>'.[/dim]",
        )
        return None

    try:
        meta = oidc.discover(credential.issuer)
        grant = oidc.client_credentials_grant(
            meta.token_endpoint,
            credential.client_id,
            credential.client_secret,
            scope=credential.scopes,
            audience=credential.audience,
        )
    except oidc.OidcError as exc:
        _warn_once(
            handle,
            f"[yellow]Could not obtain a token for @{handle}:[/yellow] {exc} "
            "[dim](continuing without one)[/dim]",
        )
        return None

    save_token(
        StoredToken(
            access_token=grant.access_token,
            issuer=meta.issuer,
            client_id=credential.client_id,
            # client_credentials issues no refresh token — an expired agent token
            # is re-minted from the client itself, which is the whole point.
            expires_at=grant.expires_at,
            token_endpoint=meta.token_endpoint,
            scope=grant.scope or credential.scopes,
        ),
        token_cache_path(handle),
    )
    return grant.access_token


def access_token(config: MyceliumConfig, handle: str | None = None) -> str | None:
    """The bearer token an agent should send, or ``None`` when it has no credential.

    Re-minted transparently once the cached one is close enough to expiry that it
    could die in flight.
    """
    credential = resolve(config, handle)
    if credential is None:
        return None
    if credential.token:
        return credential.token

    resolved_handle = credential.handle
    return _cached_token(resolved_handle, credential) or _mint(resolved_handle, credential)


def describe(config: MyceliumConfig, handle: str) -> dict[str, Any]:
    """What credential an agent resolves to, for ``agent credential show``."""
    credential = resolve(config, handle)
    if credential is None:
        return {"handle": normalize_handle(handle) or handle, "configured": False}
    cached = None
    if not credential.token:
        from mycelium.tokens import load_token

        stored = load_token(token_cache_path(credential.handle))
        if stored is not None:
            remaining = stored.expires_in()
            cached = {
                "expires_at": stored.expires_at,
                "expires_in_s": None if remaining is None else max(0.0, round(remaining)),
                "expired": stored.is_expired(),
            }
    return {"configured": True, **credential.redacted(), "cached_token": cached}
