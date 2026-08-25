# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""POST /rooms/{room}/a2a-agents — register an external A2A agent.

Like the engine route, an A2A agent is backend-owned, so the web UI registers
one directly. The extra step is card resolution: a bad endpoint must fail at
registration. Card resolution itself is mocked here so the tests stay hermetic;
the live wire is exercised by the env-gated test at the bottom.
"""

import os

import pytest

from app.services import a2a_card
from app.services.a2a_card import A2aCardError, ResolvedCard, ResolvedSkill

_FAKE_CARD = ResolvedCard(
    name="Research Agent",
    version="1.2.0",
    endpoint="https://remote.example/rpc",
    protocol_binding="JSONRPC",
    card_path="/.well-known/agent-card.json",
    streaming=True,
    description="Does research.",
    skills=[ResolvedSkill(id="deep_search", name="Deep Search", description="finds things")],
)


async def _make_room(client, name: str = "portfolio") -> None:
    resp = await client.post("/api/rooms", json={"name": name})
    assert resp.status_code in (200, 201)


@pytest.fixture
def stub_card(monkeypatch):
    async def _fake_resolve(url, **_kwargs):
        return _FAKE_CARD

    monkeypatch.setattr("app.routes.a2a_agents.resolve_card", _fake_resolve)


@pytest.mark.asyncio
async def test_register_a2a_agent_resolves_and_lists(client, stub_card):
    await _make_room(client)

    resp = await client.post(
        "/api/rooms/portfolio/a2a-agents",
        json={"handle": "researcher", "card": "https://remote.example"},
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["handle"] == "researcher"
    assert body["adapter"] == "a2a"
    assert body["a2a_endpoint"] == "https://remote.example/rpc"
    assert body["a2a_skills"] == ["deep_search"]
    # description falls back to the card's when not overridden
    assert body["description"] == "Does research."

    # It surfaces in the structured agents listing with its a2a fields.
    agents = (await client.get("/api/rooms/portfolio/agents")).json()
    row = next(a for a in agents if a["handle"] == "researcher")
    assert row["adapter"] == "a2a"
    assert row["a2a_card"] == "https://remote.example"
    assert row["a2a_skills"] == ["deep_search"]


@pytest.mark.asyncio
async def test_description_override_wins(client, stub_card):
    await _make_room(client)
    resp = await client.post(
        "/api/rooms/portfolio/a2a-agents",
        json={"handle": "researcher", "card": "https://remote.example", "description": "mine"},
    )
    assert resp.json()["description"] == "mine"


@pytest.mark.asyncio
async def test_unreachable_card_is_502(client, monkeypatch):
    await _make_room(client)

    async def _boom(url, **_kwargs):
        raise A2aCardError("no Agent Card at https://nope")

    monkeypatch.setattr("app.routes.a2a_agents.resolve_card", _boom)
    resp = await client.post(
        "/api/rooms/portfolio/a2a-agents",
        json={"handle": "researcher", "card": "https://nope"},
    )
    assert resp.status_code == 502
    assert "resolve" in resp.json()["detail"].lower()


@pytest.mark.asyncio
async def test_duplicate_handle_conflicts(client, stub_card):
    await _make_room(client)
    body = {"handle": "researcher", "card": "https://remote.example"}
    assert (await client.post("/api/rooms/portfolio/a2a-agents", json=body)).status_code == 201
    assert (await client.post("/api/rooms/portfolio/a2a-agents", json=body)).status_code == 409


@pytest.mark.asyncio
async def test_invalid_handle_rejected(client, stub_card):
    await _make_room(client)
    resp = await client.post(
        "/api/rooms/portfolio/a2a-agents",
        json={"handle": "Bad Handle!", "card": "https://remote.example"},
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_missing_room_404(client, stub_card):
    resp = await client.post(
        "/api/rooms/nope/a2a-agents",
        json={"handle": "researcher", "card": "https://remote.example"},
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_owner_defaults_to_registrar(client, stub_card):
    """When owner is omitted, it is set to created_by so the allow_from exemption works."""
    await _make_room(client)
    resp = await client.post(
        "/api/rooms/portfolio/a2a-agents",
        json={
            "handle": "researcher",
            "card": "https://remote.example",
            "created_by": "selina",
            "allow_from": ["avery"],
            # owner intentionally omitted
        },
    )
    assert resp.status_code == 201
    assert resp.json()["owner"] == "selina"


@pytest.mark.asyncio
async def test_explicit_owner_wins_over_registrar(client, stub_card):
    """An explicit owner in the payload takes precedence over created_by."""
    await _make_room(client)
    resp = await client.post(
        "/api/rooms/portfolio/a2a-agents",
        json={
            "handle": "researcher",
            "card": "https://remote.example",
            "created_by": "selina",
            "owner": "avery",
        },
    )
    assert resp.status_code == 201
    assert resp.json()["owner"] == "avery"


@pytest.mark.asyncio
async def test_session_qualified_owner_stored_as_bare(client, stub_card):
    """A session-qualified owner/created_by must be stored as a bare slug."""
    await _make_room(client)
    resp = await client.post(
        "/api/rooms/portfolio/a2a-agents",
        json={
            "handle": "researcher",
            "card": "https://remote.example",
            "created_by": "selina#abc123",
            "allow_from": ["avery#xyz"],
        },
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["owner"] == "selina"
    assert body["allow_from"] == ["avery"]


@pytest.mark.asyncio
async def test_non_http_card_scheme_rejected():
    """Hermetic: the scheme guard trips before any network I/O."""
    with pytest.raises(A2aCardError):
        await a2a_card.resolve_card("ftp://nope")


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1:8080",
        "http://169.254.169.254/latest/meta-data",  # cloud metadata endpoint
        "http://localhost:9000",
        "http://[::1]:8080",
    ],
)
@pytest.mark.asyncio
async def test_private_host_card_rejected_ssrf(url):
    """SSRF guard: a card host resolving to a non-public address is refused."""
    with pytest.raises(A2aCardError, match="SSRF|non-public|did not resolve"):
        await a2a_card.resolve_card(url)


@pytest.mark.asyncio
async def test_ssrf_guard_can_be_opted_out(monkeypatch):
    """A trusted internal deployment can allow private hosts; then the guard is a no-op
    and resolution proceeds (and fails later on the unreachable host, not the guard)."""
    monkeypatch.setattr("app.config.settings.A2A_ALLOW_PRIVATE_HOSTS", True)
    with pytest.raises(A2aCardError, match="no Agent Card|did not resolve"):
        await a2a_card.resolve_card("http://127.0.0.1:9")


@pytest.mark.skipif(
    os.getenv("MYCELIUM_A2A_LIVE") != "1",
    reason="live A2A wire test; set MYCELIUM_A2A_LIVE=1 to run",
)
@pytest.mark.asyncio
async def test_resolve_live_public_agent():
    card = await a2a_card.resolve_card("https://hello-world-gxfr.onrender.com")
    assert card.name == "Hello World Agent"
    assert "hello_world" in card.skill_ids
    # confirms the old-path fallback is still exercised end to end
    assert card.card_path == a2a_card.OLD_CARD_PATH
