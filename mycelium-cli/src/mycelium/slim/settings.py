# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""Turn the authored ``[slim]`` config into the environment the identity layer reads.

:mod:`mycelium.slim.identity` and its backend twin resolve everything from the
environment, byte-for-byte alike, so neither copy has to know what a
``config.toml`` or a pydantic ``Settings`` looks like. This module is the CLI's
one adapter between the two: it maps the authored ``[slim]`` block onto those
variable names, once, for both consumers —

* the local process, via :func:`apply_identity_env`, so a CLI joining a channel
  on this machine honours the file the operator edited; and
* the containers, via ``mycelium config apply`` → ``.env``
  (``mycelium.docker_utils``), which renders the same mapping.

The issuer and audience fall back to the HTTP plane's — ``[agent_auth]``, then
``[login]``. A member's channel identity and its API identity come from the same
credential, so making the operator restate the trust root for the second plane
would only be a way to get them out of sync.

An environment variable that is already set always wins: env over file is how
every other setting here resolves, and a container's explicit
``MYCELIUM_SLIM_IDENTITY_TOKEN`` must not be clobbered by a stale config file.
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

from mycelium.slim import identity as slim_identity

if TYPE_CHECKING:
    from mycelium.config import MyceliumConfig


def identity_issuer(config: MyceliumConfig) -> str | None:
    """The trust root peers' channel tokens are checked against."""
    return config.slim.identity_issuer or config.agent_auth.issuer or config.login.issuer


def identity_audience(config: MyceliumConfig) -> str | None:
    """The audience peers' channel tokens must carry."""
    return config.slim.identity_audience or config.agent_auth.audience or config.login.audience


def identity_env(config: MyceliumConfig) -> dict[str, str]:
    """The ``MYCELIUM_SLIM_IDENTITY*`` variables ``[slim]`` implies.

    Values that aren't configured are rendered empty rather than omitted, so a
    caller writing an env file emits ``KEY=`` and the identity layer reads it as
    unset — the same thing an absent key means.
    """
    slim = config.slim
    return {
        slim_identity.IDENTITY_ENV: slim.identity,
        slim_identity.TOKEN_FILE_ENV: slim.identity_token_file or "",
        slim_identity.ISSUER_ENV: identity_issuer(config) or "",
        slim_identity.AUDIENCE_ENV: identity_audience(config) or "",
        slim_identity.JWKS_ENV: slim.identity_jwks or "",
        slim_identity.JWKS_FILE_ENV: slim.identity_jwks_file or "",
        slim_identity.ALGORITHM_ENV: slim.identity_algorithm,
        slim_identity.DURATION_ENV: str(slim.identity_duration_s),
    }


def apply_identity_env(config: MyceliumConfig) -> dict[str, str]:
    """Publish ``[slim]``'s identity settings into this process's environment.

    Returns what was set. Variables already present are left alone and are not
    reported, so an explicitly exported value keeps winning over the file.
    """
    applied: dict[str, str] = {}
    for key, value in identity_env(config).items():
        if not value or os.environ.get(key):
            continue
        os.environ[key] = value
        applied[key] = value
    return applied
