# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""The credential seam speaks the schemes real trackers use, not just Bearer.

Two levels of proof. The scheme classes are pure, so their headers are asserted
directly. But a header the runtime *renders* is not yet a header on the wire, so
the wire tests drive a provider through the whole runtime path and read the
request off an ``httpx.MockTransport``: the runtime resolves the credential
name(s), the scheme renders them, the factory binds them, and the header that
actually leaves is the one asserted. That is the only way to catch a raw token
that renders fine but never reaches the request, or a no-auth provider that
quietly sends something.
"""

from __future__ import annotations

import base64
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta

import httpx
import pytest

from app.services.status.auth import AuthScheme, Basic, Bearer, Header
from app.services.status.context import HttpContext, build_http_context
from app.services.status.runtime import StatusRuntime
from app.services.status.types import Context, Liveness, Ok, Outcome, Ref, StatusProvider

NOW = datetime(2026, 8, 22, 12, 0, tzinfo=UTC)


# ── the scheme classes are pure: assert their headers directly ────────────────


def test_bearer_names_one_credential_and_prefixes_it():
    scheme = Bearer("GITHUB_TOKEN")
    assert scheme.names() == ("GITHUB_TOKEN",)
    assert scheme.headers({"GITHUB_TOKEN": "ghp_x"}) == {"Authorization": "Bearer ghp_x"}


def test_basic_names_two_credentials_and_base64s_identity_colon_secret():
    scheme = Basic("JIRA_EMAIL", "JIRA_TOKEN")
    # Two names, because Basic is an identity plus a secret, not one opaque string.
    assert scheme.names() == ("JIRA_EMAIL", "JIRA_TOKEN")
    rendered = scheme.headers({"JIRA_EMAIL": "user@example.com", "JIRA_TOKEN": "tok"})
    expected = base64.b64encode(b"user@example.com:tok").decode("ascii")
    assert rendered == {"Authorization": f"Basic {expected}"}


def test_header_default_is_a_raw_token_under_authorization():
    # Linear: the token, no scheme word, under Authorization.
    scheme = Header("LINEAR_TOKEN")
    assert scheme.names() == ("LINEAR_TOKEN",)
    assert scheme.headers({"LINEAR_TOKEN": "lin_abc"}) == {"Authorization": "lin_abc"}


def test_header_can_place_the_key_under_a_custom_header():
    scheme = Header("API_KEY", header="X-Api-Key")
    assert scheme.headers({"API_KEY": "k3y"}) == {"X-Api-Key": "k3y"}


def test_header_prefix_covers_pagerdutys_token_token_form():
    scheme = Header("PD_TOKEN", prefix="Token token=")
    assert scheme.headers({"PD_TOKEN": "pd_1"}) == {"Authorization": "Token token=pd_1"}


# ── the wire: what actually leaves the process for each scheme shape ───────────


class Ping:
    """A minimal provider that makes one request, so a test can read its headers."""

    name = "ping"
    max_batch = 10
    ttl = timedelta(minutes=1)
    swr = timedelta(minutes=30)

    def __init__(self, auth: AuthScheme | None, base_url: str = "https://ping.example") -> None:
        self.auth = auth
        self.base_url = base_url

    def claims(self, text: str) -> list[Ref]:
        return []

    async def fetch(self, refs: list[Ref], ctx: Context) -> list[Outcome]:
        await ctx.http.get("/probe")
        return [Ok(ref=r, liveness=Liveness(state="ok", label="ok")) for r in refs]


class _Wire:
    """Captures the request that reached the transport, and whether one did."""

    def __init__(self) -> None:
        self.headers = httpx.Headers()
        self.called = False

    def factory(self, provider: StatusProvider, auth: Mapping[str, str] | None) -> HttpContext:
        def handler(request: httpx.Request) -> httpx.Response:
            self.called = True
            self.headers = request.headers
            return httpx.Response(200, json={})

        return build_http_context(provider, auth, transport=httpx.MockTransport(handler))


async def send(provider: Ping, credentials: dict[str, str]) -> _Wire:
    wire = _Wire()
    rt = StatusRuntime(
        providers={provider.name: provider},
        context_factory=wire.factory,
        credentials=credentials,
    )
    await rt.resolve([Ref(provider=provider.name, kind="x", id="1")], NOW)
    await rt.aclose()
    return wire


@pytest.mark.asyncio
async def test_bearer_puts_bearer_token_on_the_wire():
    wire = await send(Ping(Bearer("GITHUB_TOKEN")), {"GITHUB_TOKEN": "ghp_x"})
    assert wire.headers["authorization"] == "Bearer ghp_x"


@pytest.mark.asyncio
async def test_basic_puts_the_base64_of_identity_and_secret_on_the_wire():
    wire = await send(
        Ping(Basic("JIRA_EMAIL", "JIRA_TOKEN"), base_url="https://org.atlassian.net"),
        {"JIRA_EMAIL": "user@example.com", "JIRA_TOKEN": "tok"},
    )
    expected = base64.b64encode(b"user@example.com:tok").decode("ascii")
    assert wire.headers["authorization"] == f"Basic {expected}"


@pytest.mark.asyncio
async def test_a_raw_token_and_no_auth_are_different_bytes_on_the_wire():
    # The distinction the bare-Bearer seam erased: a raw token is a header that
    # is present with no scheme word; no auth is the header absent entirely. A
    # Linear provider that declared a raw token must not go out unauthenticated.
    raw = await send(Ping(Header("LINEAR_TOKEN")), {"LINEAR_TOKEN": "lin_abc"})
    assert raw.headers["authorization"] == "lin_abc"

    none = await send(Ping(None), {})
    assert "authorization" not in none.headers


@pytest.mark.asyncio
async def test_a_custom_header_key_rides_its_own_header_not_authorization():
    wire = await send(Ping(Header("API_KEY", header="X-Api-Key")), {"API_KEY": "k3y"})
    assert wire.headers["x-api-key"] == "k3y"
    assert "authorization" not in wire.headers


@pytest.mark.asyncio
async def test_pagerdutys_token_token_form_rides_authorization():
    wire = await send(Ping(Header("PD_TOKEN", prefix="Token token=")), {"PD_TOKEN": "pd_1"})
    assert wire.headers["authorization"] == "Token token=pd_1"


# ── "configured" under a two-value credential is all-of, checked up front ──────


@pytest.mark.asyncio
async def test_basic_with_only_the_identity_set_is_refused_before_any_request():
    # Configured means every name the scheme needs, not just one. The email is
    # present, the token is not, so the runtime refuses the chunk and no request
    # is spent discovering the gap.
    provider = Ping(Basic("JIRA_EMAIL", "JIRA_TOKEN"), base_url="https://org.atlassian.net")
    wire = await send(provider, {"JIRA_EMAIL": "user@example.com"})
    assert wire.called is False


@pytest.mark.asyncio
async def test_the_missing_credential_error_names_the_absent_value():
    provider = Ping(Basic("JIRA_EMAIL", "JIRA_TOKEN"), base_url="https://org.atlassian.net")
    ref = Ref(provider=provider.name, kind="x", id="1")
    rt = StatusRuntime(
        providers={provider.name: provider},
        context_factory=lambda p, auth: build_http_context(p, auth),
        credentials={"JIRA_EMAIL": "user@example.com"},
    )
    answers = await rt.resolve([ref], NOW)
    await rt.aclose()
    assert answers[ref].freshness == "error"
    assert "JIRA_TOKEN not configured" in (answers[ref].error or "")
    # The one that is present is not named as missing.
    assert "JIRA_EMAIL" not in (answers[ref].error or "")
