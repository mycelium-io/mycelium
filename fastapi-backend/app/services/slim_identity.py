# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""SLIM channel identity: the shared-secret PSK, or a per-member JWT.

Two identity tiers stand behind one seam, chosen by ``MYCELIUM_SLIM_IDENTITY``:

``psk`` (the default)
    The deterministic shared secret every member of a room derives offline
    (:func:`~app.services.slim_client.mint_shared_secret`). Zero infrastructure,
    which is what the try-it path needs — but it is scoped to ``workspace/room``,
    so every member of a room is cryptographically indistinguishable and
    revoking one means rotating the secret for all.

``jwt``
    Each member presents its **own bearer token** as its channel identity, and
    verifies its peers' tokens against a trusted issuer. Identity is the token's
    ``sub`` — the agent or human handle — so members are distinct MLS
    participants and revoking one leaves the rest untouched.

The token is deliberately **not a new credential**: it is the same OIDC token the
HTTP plane already resolves (``mycelium.client`` / ``mycelium.agent_credentials``
on the CLI side, ``MYCELIUM_SLIM_IDENTITY_TOKEN`` for the always-on backend
moderator). One ``mycelium login`` — or one agent service account — authenticates
the API *and* joins the channel.

slim-bindings takes the presenting side as
``IdentityProviderConfig.STATIC_JWT(StaticJwtAuth(token_file=…))``: a bearer
token read from a file and reloaded when it changes. So a token resolved in
memory is materialized to an owner-only file under the data dir first
(:func:`materialize_token`), and a refreshed token is picked up by rewriting it.

Resolution is **env-only on both sides** — the same shape
``MYCELIUM_SLIM_MASTER_SECRET`` already has — so this module and its CLI mirror
(``mycelium/slim/identity.py``) stay byte-for-byte comparable. Operators author
the values under ``[slim]`` in ``config.toml``; ``mycelium config apply``
renders them into the container env. The names and defaults are frozen in
``contracts/slim-l9-wire.json``.
"""

from __future__ import annotations

import datetime
import logging
import os
import re
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import slim_bindings

    from app.services.slim_client import SlimIdentity

logger = logging.getLogger(__name__)

#: The shared-secret tier: what ships, and what every default install runs.
IDENTITY_MODE_PSK = "psk"

#: The per-member tier: each member presents its own OIDC token.
IDENTITY_MODE_JWT = "jwt"

IDENTITY_MODES = (IDENTITY_MODE_PSK, IDENTITY_MODE_JWT)

#: Which tier to use. Unset means :data:`IDENTITY_MODE_PSK` — turning JWT
#: identity on must be a deliberate act, never something an install drifts into.
IDENTITY_ENV = "MYCELIUM_SLIM_IDENTITY"

#: The member's own bearer token, verbatim. The moderator's service account
#: arrives this way; a CLI member passes its resolved token in code instead.
TOKEN_ENV = "MYCELIUM_SLIM_IDENTITY_TOKEN"

#: A file already holding the raw token — a SPIRE sidecar's JWT-SVID, or a CI
#: runner's. Used as-is: nothing here mints or renews it, and it is handed
#: straight to slim-bindings, which reloads it when the writer rewrites it.
TOKEN_FILE_ENV = "MYCELIUM_SLIM_IDENTITY_TOKEN_FILE"

#: The ``iss`` a peer's token must carry to be accepted.
ISSUER_ENV = "MYCELIUM_SLIM_IDENTITY_ISSUER"

#: The ``aud`` a peer's token must carry to be accepted.
AUDIENCE_ENV = "MYCELIUM_SLIM_IDENTITY_AUDIENCE"

#: Inline JWKS JSON for verifying peers. Unset falls back to autoresolve.
JWKS_ENV = "MYCELIUM_SLIM_IDENTITY_JWKS"

#: A file holding the JWKS, for a key set too large to sit in the environment.
JWKS_FILE_ENV = "MYCELIUM_SLIM_IDENTITY_JWKS_FILE"

#: Signing algorithm of the issuer's keys.
ALGORITHM_ENV = "MYCELIUM_SLIM_IDENTITY_ALGORITHM"

#: How long slim-bindings treats a presented identity as good for.
DURATION_ENV = "MYCELIUM_SLIM_IDENTITY_DURATION_S"

#: Refuse to fall back to the PSK when JWT identity was asked for and no token
#: could be resolved. The twin of ``MYCELIUM_SLIM_REQUIRE_SECRET``: a host that
#: means to run on verified identity fails closed rather than quietly joining
#: with a credential anyone with the repo can derive.
REQUIRE_ENV = "MYCELIUM_SLIM_IDENTITY_REQUIRE"

#: Where the materialized token files live, under the data dir.
TOKEN_DIR_NAME = "slim-identity"

DEFAULT_ALGORITHM = "RS256"
DEFAULT_DURATION_S = 3600.0

#: Handles are lowercase slugs, but the filename is derived from caller input,
#: so anything outside the slug alphabet is folded away before it reaches a path.
_UNSAFE = re.compile(r"[^A-Za-z0-9._-]+")

#: One warning per process per reason — every room provisions its own app and
#: each would otherwise repeat the same line.
_warned: set[str] = set()


class SlimIdentityError(RuntimeError):
    """SLIM identity is misconfigured, or JWT identity has nothing to present."""


def _env(name: str) -> str | None:
    return os.environ.get(name, "").strip() or None


def _truthy(value: str | None) -> bool:
    return (value or "").strip().lower() not in ("", "0", "false", "no")


def _warn_once(key: str, message: str, *args: object) -> None:
    if key in _warned:
        return
    _warned.add(key)
    logger.warning(message, *args)


def resolve_mode() -> str:
    """Which identity tier this process runs on. Defaults to the PSK."""
    raw = (_env(IDENTITY_ENV) or IDENTITY_MODE_PSK).lower()
    if raw not in IDENTITY_MODES:
        raise SlimIdentityError(
            f"{IDENTITY_ENV}={raw!r} is not a SLIM identity mode; "
            f"expected one of {', '.join(IDENTITY_MODES)}"
        )
    return raw


def data_dir() -> Path:
    """The mycelium data dir the token file is written under."""
    override = _env("MYCELIUM_DATA_DIR")
    return Path(override).expanduser() if override else Path.home() / ".mycelium"


def token_file_path(agent: str) -> Path:
    """Where ``agent``'s presented token is materialized, one file per agent.

    Keyed on the agent rather than the channel: one credential is the same
    identity in every room it joins, so all its rooms read one file and a
    refresh is written once.
    """
    safe = _UNSAFE.sub("-", agent) or "agent"
    return data_dir() / TOKEN_DIR_NAME / f"{safe}.jwt"


def materialize_token(agent: str, token: str) -> Path:
    """Write ``token`` where slim-bindings can read it, owner-only.

    Rewritten only when the contents actually change: slim-bindings watches the
    file and reloads on change, so re-writing an identical token on every
    connect would churn the identity for no reason.
    """
    path = token_file_path(agent)
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        if path.read_text(encoding="utf-8") == token:
            return path
    except OSError:
        pass
    # os.open with 0600 rather than write_text + chmod: the file must never
    # exist, even momentarily, with the default mode — it holds a bearer token.
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write(token)
    # A file written before this mode was asserted keeps its old one otherwise.
    os.chmod(path, 0o600)
    return path


@dataclass(frozen=True)
class JwtIdentity:
    """Everything the JWT tier needs: what to present, and what to accept."""

    #: The bearer token to present, in memory. Materialized before use.
    token: str | None = None
    #: A file already holding the token, used as-is instead of materializing.
    token_file: str | None = None
    issuer: str | None = None
    audience: str | None = None
    jwks: str | None = None
    jwks_file: str | None = None
    algorithm: str = DEFAULT_ALGORITHM
    duration_s: float = DEFAULT_DURATION_S

    def has_token(self) -> bool:
        return bool(self.token or self.token_file)


def resolve_jwt_identity(*, token: str | None = None) -> JwtIdentity:
    """The JWT tier's settings, from the environment and an in-memory token.

    ``token`` is what the caller already resolved for the HTTP plane — an
    agent's service-account token or the human session. It wins over the
    environment, which is how one process can join as several distinct members.
    """
    raw_duration = _env(DURATION_ENV)
    try:
        duration_s = float(raw_duration) if raw_duration else DEFAULT_DURATION_S
    except ValueError:
        raise SlimIdentityError(f"{DURATION_ENV}={raw_duration!r} is not a number")
    if duration_s <= 0:
        raise SlimIdentityError(f"{DURATION_ENV}={raw_duration!r} must be positive")

    return JwtIdentity(
        token=token or _env(TOKEN_ENV),
        token_file=_env(TOKEN_FILE_ENV),
        issuer=_env(ISSUER_ENV),
        audience=_env(AUDIENCE_ENV),
        jwks=_env(JWKS_ENV),
        jwks_file=_env(JWKS_FILE_ENV),
        algorithm=(_env(ALGORITHM_ENV) or DEFAULT_ALGORITHM).upper(),
        duration_s=duration_s,
    )


def _algorithm(sb: ModuleType, name: str) -> slim_bindings.JwtAlgorithm:
    try:
        return getattr(sb.JwtAlgorithm, name)
    except AttributeError:
        raise SlimIdentityError(
            f"{ALGORITHM_ENV}={name!r} is not a JWT algorithm slim-bindings knows"
        )


def build_provider(
    sb: ModuleType, jwt: JwtIdentity, *, agent: str
) -> slim_bindings.IdentityProviderConfig:
    """How this member proves who it is: its bearer token, from a file.

    An in-memory token is materialized under the data dir; a ``token_file`` the
    caller already has (a SPIRE sidecar's JWT-SVID) is passed through untouched.
    """
    if jwt.token_file:
        path = jwt.token_file
    elif jwt.token:
        path = str(materialize_token(agent, jwt.token))
    else:
        raise SlimIdentityError("JWT channel identity needs a token and none was resolved")
    return sb.IdentityProviderConfig.STATIC_JWT(
        sb.StaticJwtAuth(
            token_file=path,
            duration=datetime.timedelta(seconds=jwt.duration_s),
        )
    )


def build_verifier(sb: ModuleType, jwt: JwtIdentity) -> slim_bindings.IdentityVerifierConfig:
    """How this member decides a peer's token is real.

    An explicitly configured JWKS (inline or a file) pins the keys. With none,
    the key is autoresolved from the token's issuer — which is why ``issuer``
    and ``audience`` matter: they are what bounds who may be believed.
    """
    if jwt.jwks or jwt.jwks_file:
        data = sb.JwtKeyData.DATA(jwt.jwks) if jwt.jwks else sb.JwtKeyData.FILE(str(jwt.jwks_file))
        key = sb.JwtKeyType.DECODING(
            sb.JwtKeyConfig(
                algorithm=_algorithm(sb, jwt.algorithm),
                format=sb.JwtKeyFormat.JWKS,
                key=data,
            )
        )
    else:
        key = sb.JwtKeyType.AUTORESOLVE()
    return sb.IdentityVerifierConfig.JWT(
        sb.JwtAuth(
            key=key,
            audience=[jwt.audience] if jwt.audience else None,
            issuer=jwt.issuer,
            subject=None,
            duration=datetime.timedelta(seconds=jwt.duration_s),
        )
    )


def build_connection_auth(
    sb: ModuleType, jwt: JwtIdentity, *, agent: str
) -> slim_bindings.ClientAuthenticationConfig:
    """The same token again, this time for the connection to the node.

    App identity and transport are separate axes in SLIM: the provider/verifier
    pair above is what MLS peers check about each other, and the node forwards
    ciphertext without needing any of it. A node *may* additionally gate the
    dataplane connection itself (``auth.jwt`` on its server config), and a client
    that presents nothing is refused there. Carrying the token on both means one
    credential covers the whole path.
    """
    if jwt.token_file:
        path = jwt.token_file
    elif jwt.token:
        path = str(materialize_token(agent, jwt.token))
    else:
        raise SlimIdentityError("JWT channel identity needs a token and none was resolved")
    return sb.ClientAuthenticationConfig.STATIC_JWT(
        sb.StaticJwtAuth(
            token_file=path,
            duration=datetime.timedelta(seconds=jwt.duration_s),
        )
    )


@dataclass(frozen=True)
class ChannelIdentity:
    """What an app presents and accepts once the JWT tier is in force."""

    #: Proves this member's identity to its MLS peers.
    provider: slim_bindings.IdentityProviderConfig
    #: Decides whether a peer's presented identity is believable.
    verifier: slim_bindings.IdentityVerifierConfig
    #: Proves the same identity to the node, for a node that gates connections.
    connection_auth: slim_bindings.ClientAuthenticationConfig


def build_configs(
    sb: ModuleType, identity: SlimIdentity, *, token: str | None = None
) -> ChannelIdentity | None:
    """What ``identity`` presents on the channel, or ``None`` to use the PSK.

    ``None`` covers both off-by-default cases: the PSK tier is selected, or JWT
    identity is selected but this member has no token to present — against an
    issuer-less install that is exactly today's behavior, so it degrades to the
    PSK with a warning rather than refusing to join. Set
    ``MYCELIUM_SLIM_IDENTITY_REQUIRE`` to make that degradation an error instead.
    """
    if resolve_mode() != IDENTITY_MODE_JWT:
        return None

    jwt = resolve_jwt_identity(token=token)
    if not jwt.has_token():
        if _truthy(_env(REQUIRE_ENV)):
            raise SlimIdentityError(
                f"{IDENTITY_ENV}={IDENTITY_MODE_JWT} and {REQUIRE_ENV} is set, but no token "
                f"could be resolved for @{identity.agent}: refusing to fall back to the "
                "shared-secret PSK."
            )
        _warn_once(
            f"no-token:{identity.agent}",
            "JWT channel identity is enabled but @%s has no token to present — "
            "joining with the shared-secret PSK instead. Set %s (or log in / give the "
            "agent a credential); set %s to fail closed here.",
            identity.agent,
            TOKEN_ENV,
            REQUIRE_ENV,
        )
        return None

    return ChannelIdentity(
        provider=build_provider(sb, jwt, agent=identity.agent),
        verifier=build_verifier(sb, jwt),
        connection_auth=build_connection_auth(sb, jwt, agent=identity.agent),
    )
