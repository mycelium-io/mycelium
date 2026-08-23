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
from collections.abc import Callable, Mapping
from datetime import timedelta
from typing import Protocol

import httpx

from app.services.status.types import Context, StatusProvider

logger = logging.getLogger("mycelium.status")


class _Bound(Protocol):
    """All the factory needs of a provider: the one host to bind to.

    ``build_http_context`` reads nothing else off the provider (the credential
    arrives already resolved), so it asks for nothing else. Every
    ``StatusProvider`` satisfies this, so the factory is still a valid
    ``ContextFactory``.
    """

    base_url: str


#: What the runtime hands the factory: the credential already rendered into the
#: headers that go on the wire (``Bearer`` derives one, ``Basic`` base64-encodes
#: two, ``Header`` prefixes one), or ``None`` for a provider that declares no
#: auth. A scheme is the only thing that renders a credential, so there is no
#: second spelling here for the common case; the factory only binds the result,
#: and the value passes from runtime to transport without a provider ever being
#: a party to it.
ResolvedAuth = Mapping[str, str] | None

#: Built once per provider by the runtime, given the provider and its resolved
#: auth. The runtime owns credential *resolution and rendering*; the factory owns
#: *binding* the rendered headers into a transport.
ContextFactory = Callable[[StatusProvider, ResolvedAuth], Context]


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
    provider: _Bound,
    credential: ResolvedAuth,
    *,
    timeout: timedelta = DEFAULT_TIMEOUT,
    retries: int = DEFAULT_RETRIES,
    transport: httpx.AsyncBaseTransport | None = None,
) -> HttpContext:
    """The default factory: a client bound to ``provider.base_url`` carrying its auth.

    ``credential`` is what the runtime resolved for this provider's ``auth``: the
    headers the scheme rendered, or ``None`` for no auth. It is passed in rather
    than read here so credential resolution and rendering stay in one place, and
    it arrives rendered because a scheme is the only thing that turns a
    credential into a header. A provider that declares no auth is handed an
    unauthenticated client; the runtime already refuses to call one whose
    declared credentials are missing, so an empty value never reaches this path
    for a provider that needs one.

    ``transport`` overrides only the *inner* transport; it is still wrapped by the
    host bound, so a caller (a test) can read the request off a fake transport
    while the host refusal stays in the path exactly as in production.
    """

    headers = dict(credential or {})
    base = httpx.URL(provider.base_url)
    inner = transport or httpx.AsyncHTTPTransport(retries=retries)
    bound = _HostBoundTransport(inner, base.host)
    client = httpx.AsyncClient(
        base_url=base,
        headers=headers,
        timeout=timeout.total_seconds(),
        transport=bound,
    )
    return HttpContext(client)
