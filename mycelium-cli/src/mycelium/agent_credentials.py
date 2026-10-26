# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""
Per-agent credentials: an agent's *own* token, resolved at the one client seam.

A human runs ``mycelium login`` and gets a session. An agent can't: there is no
browser to open, no consent screen to click, and nobody sitting there to do it.
So an agent authenticates as a **workload**: its own OIDC client, minted with the
``client_credentials`` grant, whose ``sub`` is the client id, which is the
agent's handle, the same handle the hub binds its writes to
(``app/services/actor.py``). Two agents on one machine therefore hold two
different credentials, and revoking one client leaves the other untouched.

Three sources, most specific first:

* **A pre-minted token** (``MYCELIUM_AGENT_AUTH_TOKEN``, or the file named by
  ``MYCELIUM_AGENT_AUTH_TOKEN_FILE``). The seam for a credential this CLI
  didn't obtain: a token from CI, one a sidecar wrote out, or the member token
  the runner gets for each agent it starts (:func:`issue_member_token`).
  Nothing here mints or renews it; the writer owns its lifetime.
* **The environment** (``MYCELIUM_AGENT_AUTH_CLIENT_ID`` / ``…_CLIENT_SECRET``),
  for a container that runs exactly one agent and has no config file.
* **The credential store**, ``~/.mycelium/agent-credentials.json``, written by
  ``mycelium agent credential set``. A secret, so it is ``0600`` and lives
  outside ``config.toml`` (the same reason the human session does
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
#: The credential follows this identity rather than being separately set.
AGENT_HANDLE_ENV = "MYCELIUM_AGENT_HANDLE"

STATIC_TOKEN_ENV = "MYCELIUM_AGENT_AUTH_TOKEN"
#: A file holding the agent's token, read on every call: how the runner hands
#: an agent its own token without putting the token itself where a pane's
#: screen or a typed command would show it (:func:`issue_member_token`).
STATIC_TOKEN_FILE_ENV = "MYCELIUM_AGENT_AUTH_TOKEN_FILE"
CLIENT_ID_ENV = "MYCELIUM_AGENT_AUTH_CLIENT_ID"
CLIENT_SECRET_ENV = "MYCELIUM_AGENT_AUTH_CLIENT_SECRET"

_stderr = Console(stderr=True)

#: One warning per handle per process: every command builds several clients and
#: each would otherwise repeat the same failure.
_warned: set[str] = set()

#: Handles are lowercase slugs, but the cache path is derived from caller input,
#: so anything outside the slug alphabet is folded away before it reaches a path.
_UNSAFE = re.compile(r"[^a-z0-9._-]+")


def normalize_handle(raw: str | None) -> str | None:
    """Normalize handle, dropping session qualifier (matches ``auth.normalize_handle``)."""
    if not isinstance(raw, str):
        return None
    base = raw.partition("#")[0]
    return base.strip().lstrip("@").lower() or None


def ambient_handle() -> str | None:
    return normalize_handle(os.environ.get(AGENT_HANDLE_ENV))


def store_path() -> Path:
    override = os.environ.get(CREDENTIAL_STORE_ENV, "").strip()
    if override:
        return Path(override).expanduser()

    from mycelium.config import MyceliumConfig

    return MyceliumConfig.get_global_config_dir() / "agent-credentials.json"


def token_cache_path(handle: str) -> Path:
    """Where a minted token is cached: beside a store named by the environment,
    else in the agent-state folder, which an agent can write from a sandbox."""
    safe = _UNSAFE.sub("-", handle) or "agent"
    if os.environ.get(CREDENTIAL_STORE_ENV, "").strip():
        return store_path().parent / "agent-tokens" / f"{safe}.json"

    from mycelium.config import MyceliumConfig

    return MyceliumConfig.get_agent_state_dir() / "agent-tokens" / f"{safe}.json"


@dataclass(frozen=True)
class AgentCredential:
    """How one agent proves who it is."""

    handle: str
    client_id: str
    client_secret: str | None = None
    issuer: str | None = None
    scopes: str | None = None
    audience: str | None = None
    #: A token obtained elsewhere (CI, a sidecar). Used as-is, never minted.
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
    """Return stored agents (damaged store reads as empty)."""
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
    """Write store with 0600 permissions (holds secrets)."""
    path = store_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    # os.open with 0600 creates the file with the right permissions atomically.
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        json.dump({"agents": agents}, fh, indent=2, sort_keys=True)
        fh.write("\n")
    # Re-assert the mode on every write to cover stores from earlier versions.
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


def env_static_token() -> str | None:
    """A pre-minted token from the environment: given directly, or in the file
    the environment names. ``None`` when neither gives one."""
    token = os.environ.get(STATIC_TOKEN_ENV, "").strip()
    if token:
        return token
    path = os.environ.get(STATIC_TOKEN_FILE_ENV, "").strip()
    if not path:
        return None
    try:
        return Path(path).expanduser().read_text().strip() or None
    except OSError:
        return None


def member_token_path(room: str, handle: str) -> Path:
    """Where the runner keeps the member token it got for ``@handle`` in ``room``.

    Beside the config rather than in the agent-state folder: an agent only
    reads its token, and a sandboxed agent (Codex) can write the agent-state
    folder, so one agent there could replace another's."""
    from mycelium.config import MyceliumConfig

    safe_room = _UNSAFE.sub("-", room.lower()) or "room"
    safe_handle = _UNSAFE.sub("-", normalize_handle(handle) or "agent") or "agent"
    folder = MyceliumConfig.get_global_config_dir() / "member-tokens" / safe_room
    return folder / f"{safe_handle}.token"


class MemberTokenRefused(Exception):
    """The hub has sign-in on and won't give this agent a token for this
    machine: it isn't signed in (401), or whoever it's signed in as doesn't
    own the agent (403). Started anyway, the agent could do nothing, so
    whoever starts it says why instead."""

    def __init__(self, handle: str, hub: str, status: int, detail: str) -> None:
        self.handle, self.hub, self.status, self.detail = handle, hub, status, detail
        super().__init__(self.reason())

    @property
    def signed_out(self) -> bool:
        return self.status == 401

    def reason(self) -> str:
        if self.signed_out:
            return (
                f"This computer isn't signed in to {self.hub}, so @{self.handle} can't get "
                "its own credential there. Run `mycelium login` in a terminal here, then "
                "start it again."
            )
        return (
            f"{self.hub} won't give @{self.handle} a credential for whoever this computer "
            f"is signed in as: {self.detail} Sign in here as its owner, or start it from "
            "its owner's computer."
        )


def _hub_detail(resp: Any) -> str:
    try:
        body = resp.json()
    except ValueError:
        return resp.text.strip()[:200]
    detail = body.get("detail") if isinstance(body, dict) else None
    return str(detail)[:200] if detail else resp.text.strip()[:200]


def issue_member_token(config: MyceliumConfig, room: str, handle: str) -> Path | None:
    """Get ``@handle`` its own token for ``room`` and keep it in a file; the file's path.

    Asks the hub for a join code for the agent, as whoever this machine is
    signed in as (an agent is started by its owner), and redeems it: on a hub
    with auth on, that gives a token the hub signed for the agent itself. The
    token is written to :func:`member_token_path` (``0600``) and the pane is
    given the path in :data:`STATIC_TOKEN_FILE_ENV`, so the token is never in
    its environment listing, a typed command or its screen. ``None`` with auth
    off (no token to keep), or when the hub can't be asked; the agent then
    starts as before. Raises :class:`MemberTokenRefused` when the hub has
    sign-in on and refuses this machine, since the agent would start unable
    to do anything.
    """
    import httpx

    from mycelium.client import hub_client

    name = normalize_handle(handle) or handle
    try:
        with hub_client(config, timeout=15) as client:
            made = client.post(f"/api/rooms/{room}/joins", json={"handle": name})
        if made.status_code in (401, 403):
            raise MemberTokenRefused(
                name, config.server.api_url.rstrip("/"), made.status_code, _hub_detail(made)
            )
        if made.status_code != 201:
            _warn_once(
                name, f"[yellow]No token for @{name}:[/yellow] the hub said {made.text[:200]}"
            )
            return None
        hub_url = config.server.api_url.rstrip("/")
        # The code is the credential here: nobody's login rides on this call.
        redeemed = httpx.post(
            f"{hub_url}/api/joins/redeem", json={"code": made.json()["code"]}, timeout=15.0
        )
        redeemed.raise_for_status()
        token = redeemed.json().get("token")
    except (httpx.HTTPError, KeyError, ValueError) as e:
        _warn_once(name, f"[yellow]No token for @{name}:[/yellow] {e}")
        return None
    if not token:
        return None
    path = member_token_path(room, name)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as fh:
        fh.write(token)
    path.chmod(0o600)
    return path


def agent_token_env(config: MyceliumConfig, room: str, handle: str) -> dict[str, str]:
    """The environment that gives an agent's pane its own token: the file's
    path, or nothing when there's no token to give (auth off). Raises
    :class:`MemberTokenRefused` when the hub refuses this machine."""
    path = issue_member_token(config, room, handle)
    return {STATIC_TOKEN_FILE_ENV: str(path)} if path is not None else {}


def resolve(config: MyceliumConfig, handle: str | None = None) -> AgentCredential | None:
    """The credential an agent should present, or ``None`` when it has none.

    ``None`` is the default and the common case: no agent credential configured,
    so the caller attaches nothing and behaves as it always has.
    """
    resolved_handle = normalize_handle(handle) or ambient_handle()
    if resolved_handle is None:
        return None

    stored = list_credentials().get(resolved_handle)
    env_token = env_static_token()
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
            # client_credentials issues no refresh token; an expired agent token
            # is re-minted from the client itself, which is the whole point.
            expires_at=grant.expires_at,
            token_endpoint=meta.token_endpoint,
            scope=grant.scope or credential.scopes,
        ),
        token_cache_path(handle),
    )
    return grant.access_token


def access_token(config: MyceliumConfig, handle: str | None = None) -> str | None:
    """The agent's bearer token, or ``None`` with no credential; re-minted near expiry."""
    credential = resolve(config, handle)
    if credential is None:
        return None
    if credential.token:
        return credential.token

    resolved_handle = credential.handle
    return _cached_token(resolved_handle, credential) or _mint(resolved_handle, credential)


def describe(config: MyceliumConfig, handle: str) -> dict[str, Any]:
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
