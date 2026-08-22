# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""The concrete ``Context`` a provider is handed: a bound, credentialled transport.

This is the keystone that makes the contract runnable.  ``types.Context`` promises
a provider an ``http`` already pointed at its declared ``base_url``, already
carrying its credential, already given the timeout and retry policy, so the
provider writes request-and-parse and never a line of auth or backoff.  Nothing
implemented that promise until here.

The two guarantees the protocol makes are both enforced here rather than trusted:

* **A provider cannot reach a host it never declared.**  The client is built with
  a transport that refuses any request whose host is not ``base_url``'s, so a
  redirect or a hand-written absolute URL cannot carry the credential off to a
  third party.  Binding ``base_url`` alone would not do it: httpx will happily
  follow an absolute URL to another host, so the host check is a real gate in
  the request path, not a naming convention.

* **A provider cannot read the credential.**  It is baked into the client's
  default headers at construction and never surfaced on the ``Context``; there is
  no ``ctx.secret`` and no way back to the string from ``ctx.http``.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import timedelta

import httpx

from app.services.status.types import Context, StatusProvider

logger = logging.getLogger("mycelium.status")

#: Built once per provider by the runtime, given the provider and the resolved
#: value of its declared credential (``None`` when the provider declares none).
#: The runtime owns credential *resolution*; the factory owns *binding* it into a
#: transport, so the value passes from runtime to transport without a provider
#: ever being a party to it.
ContextFactory = Callable[[StatusProvider, str | None], Context]

DEFAULT_TIMEOUT = timedelta(seconds=10)
#: httpx retries connection failures only (never a request that got a response),
#: so this is safe against non-idempotent calls: a rate-limit or a 500 is a
#: value the provider maps, not something retried underneath it.
DEFAULT_RETRIES = 2


class HostBoundError(RuntimeError):
    """Raised when a provider's transport is asked to reach an undeclared host."""


class _HostBoundTransport(httpx.AsyncBaseTransport):
    """Wraps a real transport and refuses any host but the one declared.

    The refusal happens before the request is sent, so no bytes, and no
    credential header, leave the process bound for the wrong host.
    """

    def __init__(self, inner: httpx.AsyncBaseTransport, host: str | None) -> None:
        self._inner = inner
        self._host = host

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        if self._host is not None and request.url.host != self._host:
            raise HostBoundError(
                f"transport is bound to {self._host!r}; refusing request to {request.url.host!r}"
            )
        return await self._inner.handle_async_request(request)

    async def aclose(self) -> None:
        await self._inner.aclose()


class HttpContext:
    """A ``Context`` backed by a bound httpx client. Owns the client's lifetime."""

    def __init__(self, client: httpx.AsyncClient) -> None:
        self._client = client

    @property
    def http(self) -> httpx.AsyncClient:
        return self._client

    def log(self, message: str, **fields: object) -> None:
        logger.info(message, extra={"status_provider": fields} if fields else None)

    async def aclose(self) -> None:
        await self._client.aclose()


def build_http_context(
    provider: StatusProvider,
    credential: str | None,
    *,
    timeout: timedelta = DEFAULT_TIMEOUT,
    retries: int = DEFAULT_RETRIES,
) -> HttpContext:
    """The default factory: a client bound to ``provider.base_url`` with its token.

    ``credential`` is the *value* the runtime resolved for ``provider.credential``,
    passed in rather than read here so credential resolution stays in one place.
    A provider that declares no credential is handed an unauthenticated client;
    the runtime already refuses to call one whose declared credential is missing,
    so an empty string never reaches this path for a provider that needs one.
    """

    headers = {"Authorization": f"Bearer {credential}"} if credential else {}
    base = httpx.URL(provider.base_url)
    transport = _HostBoundTransport(httpx.AsyncHTTPTransport(retries=retries), base.host)
    client = httpx.AsyncClient(
        base_url=base,
        headers=headers,
        timeout=timeout.total_seconds(),
        transport=transport,
    )
    return HttpContext(client)
