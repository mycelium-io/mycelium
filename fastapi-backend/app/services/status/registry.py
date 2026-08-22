# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""The provider roster, and the one ``StatusRuntime`` the app runs.

Everything under ``status/`` up to here was a contract with nothing standing on
it: a provider protocol, a cache, a runtime, a credential source, and no caller.
This is the caller. It holds the list of providers the hub ships, builds the
single runtime they share, and hands it out.

**One runtime for the process.** The cache lives on the runtime, so a second one
would mean a second cache: two answers for the same pull request, each with its
own idea of how stale it is, and two fetches where the whole design exists to
make one. It is built lazily on first use rather than at import, so a test can
point the credential source somewhere else first.

**Credentials are resolved once, at build.** ``credentials.for_providers`` reads
the env and the store for exactly the names the registered providers declare. A
credential added after the runtime is built is not seen until it is rebuilt,
which is what ``reset`` is for; the hub is restarted after configuring one, and
the CLI says so.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from app.services.status import credentials
from app.services.status.providers.github import GitHubProvider
from app.services.status.runtime import ProviderConformanceError, StatusRuntime

if TYPE_CHECKING:
    from app.services.status.types import StatusProvider

logger = logging.getLogger("mycelium.status")

_runtime: StatusRuntime | None = None


def registered() -> dict[str, StatusProvider]:
    """Every provider the hub ships, by name.

    A provider is first-party code in ``providers/``, not a plugin loaded from
    disk: it runs in the backend process with the hub's credentials, so adding
    one is a code change that goes through review, not a config entry.
    """
    providers: list[StatusProvider] = [GitHubProvider()]
    return {provider.name: provider for provider in providers}


def get_runtime() -> StatusRuntime:
    """The process-wide runtime, built on first use.

    A provider that fails the conformance check would make this raise on every
    call, so it is caught and logged once and the offender is dropped: a board
    that cannot resolve GitHub is worth more than a hub that will not start.
    """
    global _runtime
    if _runtime is None:
        providers = registered()
        try:
            _runtime = StatusRuntime(
                providers=providers,
                credentials=credentials.for_providers(providers.values()),
            )
        except ProviderConformanceError:
            logger.exception("status provider registry rejected; serving no providers")
            _runtime = StatusRuntime(providers={}, credentials={})
        except credentials.CredentialStoreError:
            # A damaged store is the operator's to fix, and it is not a reason
            # for the whole hub to fail to serve. Every ref will report the
            # provider as unconfigured until it is repaired.
            logger.exception("status credential store unreadable; serving no credentials")
            _runtime = StatusRuntime(providers=registered(), credentials={})
    return _runtime


async def reset() -> None:
    """Drop the runtime, closing its transports. The next call rebuilds it."""
    global _runtime
    if _runtime is not None:
        await _runtime.aclose()
        _runtime = None
