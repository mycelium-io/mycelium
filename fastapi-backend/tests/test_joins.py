# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""Join codes, and the member tokens a gated hub signs when one is redeemed."""

from __future__ import annotations

import pytest
import yaml
from httpx import AsyncClient

from app.services import auth as auth_service
from app.services import member_tokens
from app.services.filesystem import get_room_dir, write_memory_file
from app.services.joins import CODE_TTL_S, JoinError, Joins, joins, normalize

ROOM = "join-room"


def _seed_agent(handle: str, *, owner: str | None = None, room: str = ROOM) -> None:
    body: dict[str, object] = {"adapter": "claude_code"}
    if owner is not None:
        body["owner"] = owner
    write_memory_file(
        get_room_dir(room), f"agents/{handle}", yaml.safe_dump(body), created_by="tester"
    )


@pytest.fixture(autouse=True)
def _fresh():
    joins.clear()
    member_tokens.reset_for_tests()
    yield
    joins.clear()
    member_tokens.reset_for_tests()


async def _room(client: AsyncClient, name: str = ROOM) -> None:
    resp = await client.post("/api/rooms", json={"name": name})
    assert resp.status_code in (200, 201), resp.text


# ── the codes themselves ─────────────────────────────────────────────────────


def test_a_code_is_single_use():
    table = Joins()
    code, _ = table.create(ROOM, "builder", created_by=None)
    assert table.redeem(code).handle == "builder"
    with pytest.raises(JoinError):
        table.redeem(code)


def test_a_code_expires():
    table = Joins()
    code, _ = table.create(ROOM, "builder", created_by=None, now=1000.0)
    with pytest.raises(JoinError):
        table.redeem(code, now=1000.0 + CODE_TTL_S + 1)


def test_a_code_is_read_however_it_was_typed():
    table = Joins()
    code, _ = table.create(ROOM, "builder", created_by=None)
    typed = code.upper().replace("-", " ")
    assert table.redeem(typed).handle == "builder"
    assert normalize("ABCD efgh-IJKL") == "abcd-efgh-ijkl"


def test_the_table_holds_no_code_it_could_hand_back():
    table = Joins()
    code, _ = table.create(ROOM, "builder", created_by=None)
    # The point is what's stored.
    assert code not in table._codes


# ── asking for a code ────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_a_code_names_the_room_and_member(client: AsyncClient):
    await _room(client)
    _seed_agent("builder")
    resp = await client.post(f"/api/rooms/{ROOM}/joins", json={"handle": "@Builder"})
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["room"] == ROOM
    assert body["handle"] == "builder"
    assert len(body["code"]) == 14


@pytest.mark.asyncio
async def test_no_code_for_a_handle_that_isnt_an_agent_here(client: AsyncClient):
    await _room(client)
    resp = await client.post(f"/api/rooms/{ROOM}/joins", json={"handle": "ghost"})
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_no_code_for_a_room_that_doesnt_exist(client: AsyncClient):
    resp = await client.post("/api/rooms/nowhere/joins", json={"handle": "builder"})
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_only_someone_who_may_act_as_the_member_gets_its_code(
    client: AsyncClient, as_principal
):
    await _room(client)
    _seed_agent("builder", owner="julia")
    as_principal("mallory")
    refused = await client.post(f"/api/rooms/{ROOM}/joins", json={"handle": "builder"})
    assert refused.status_code == 403
    as_principal("julia")
    allowed = await client.post(f"/api/rooms/{ROOM}/joins", json={"handle": "builder"})
    assert allowed.status_code == 201


# ── redeeming one ────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_redeeming_makes_you_the_member_without_a_token_when_auth_is_off(
    client: AsyncClient,
):
    await _room(client)
    _seed_agent("builder")
    code = (await client.post(f"/api/rooms/{ROOM}/joins", json={"handle": "builder"})).json()[
        "code"
    ]
    resp = await client.post("/api/joins/redeem", json={"code": code})
    assert resp.status_code == 200, resp.text
    assert resp.json() == {
        "room": ROOM,
        "handle": "builder",
        "token": None,
        "token_expires_at": None,
    }
    again = await client.post("/api/joins/redeem", json={"code": code})
    assert again.status_code == 400


@pytest.fixture
def gate_on(monkeypatch):
    """Gate on with one outside issuer configured, no loopback bypass."""
    from app.config import TrustedIssuer

    monkeypatch.setattr("app.config.settings.AUTH_ENABLED", True)
    monkeypatch.setattr("app.config.settings.AUTH_LOCALHOST_BYPASS", False)
    monkeypatch.setattr("app.config.settings.AUTH_AUDIENCE", None)
    monkeypatch.setattr(
        "app.config.settings.AUTH_ISSUERS",
        [
            TrustedIssuer(
                issuer="https://idp.test/realms/mycelium", jwks_url="https://idp.test/jwks"
            )
        ],
    )
    auth_service.jwks_cache.clear()


@pytest.mark.asyncio
async def test_on_a_gated_hub_redeeming_needs_no_token_and_returns_one(
    client: AsyncClient, gate_on
):
    """The redeem path is open, and the token it returns opens the rest of the API."""
    _seed_agent("builder")
    code, _ = joins.create(ROOM, "builder", created_by="julia")
    resp = await client.post("/api/joins/redeem", json={"code": code})
    assert resp.status_code == 200, resp.text
    token = resp.json()["token"]
    assert token
    assert resp.json()["token_expires_at"]

    assert (await client.get("/api/rooms")).status_code == 401
    ok = await client.get("/api/rooms", headers={"Authorization": f"Bearer {token}"})
    assert ok.status_code == 200


@pytest.mark.asyncio
async def test_a_member_token_resolves_to_the_member_as_an_agent(gate_on):
    token, _ = member_tokens.mint("builder", ROOM)
    principal = await auth_service.verify_token(token)
    assert principal.handle == "builder"
    assert principal.role == "agent"
    assert principal.issuer == member_tokens.ISSUER


@pytest.mark.asyncio
async def test_another_hubs_member_token_is_refused(gate_on):
    token, _ = member_tokens.mint("builder", ROOM)
    member_tokens.reset_for_tests()
    # A different hub is a different data dir, so a different key.
    (member_tokens._key_path()).unlink()
    with pytest.raises(auth_service.AuthError):
        await auth_service.verify_token(token)


def test_the_signing_key_is_kept_and_private():
    member_tokens.signing_key()
    path = member_tokens._key_path()
    assert path.exists()
    assert path.stat().st_mode & 0o077 == 0
    first = member_tokens.verification_key().public_numbers()
    member_tokens.reset_for_tests()
    assert member_tokens.verification_key().public_numbers() == first
