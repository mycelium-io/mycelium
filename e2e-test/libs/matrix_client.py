"""Async Matrix client for E2E test interactions."""

from __future__ import annotations

import hashlib
import hmac
import logging
import os
import uuid
from typing import Any, Optional
from urllib.parse import quote

import httpx

log = logging.getLogger(__name__)


class MatrixClient:
    """Async Matrix client for sending/reading messages in test rooms."""

    def __init__(self, homeserver: str, access_token: str):
        self.homeserver = homeserver.rstrip("/")
        self.access_token = access_token
        self._http = httpx.AsyncClient(
            base_url=self.homeserver,
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=30.0,
        )

    async def close(self):
        await self._http.aclose()

    async def send_message(
        self,
        room_id: str,
        body: str,
        msgtype: str = "m.text",
        formatted_body: Optional[str] = None,
        mention_user_ids: Optional[list] = None,
    ) -> dict:
        txn_id = uuid.uuid4().hex
        payload: dict[str, Any] = {"msgtype": msgtype, "body": body}
        if formatted_body:
            payload["format"] = "org.matrix.custom.html"
            payload["formatted_body"] = formatted_body
        # m.mentions is the Matrix spec field for explicit user mentions.
        # Clients (and bots like the OpenClaw gateway) use this to filter
        # requireMention checks — without it, mentions in formatted_body are ignored.
        if mention_user_ids:
            payload["m.mentions"] = {"user_ids": mention_user_ids}
        r = await self._http.put(
            f"/_matrix/client/v3/rooms/{quote(room_id, safe='')}/send/m.room.message/{txn_id}",
            json=payload,
        )
        r.raise_for_status()
        return r.json()

    async def read_messages(self, room_id: str, limit: int = 50, since: Optional[str] = None) -> tuple[list[dict], str]:
        params: dict[str, Any] = {"dir": "b", "limit": limit}
        if since:
            params["from"] = since
        r = await self._http.get(
            f"/_matrix/client/v3/rooms/{quote(room_id, safe='')}/messages",
            params=params,
        )
        r.raise_for_status()
        data = r.json()
        messages = []
        for ev in reversed(data.get("chunk", [])):
            if ev.get("type") == "m.room.message":
                messages.append(
                    {
                        "event_id": ev.get("event_id"),
                        "sender": ev.get("sender"),
                        "timestamp": ev.get("origin_server_ts"),
                        "body": ev.get("content", {}).get("body", ""),
                        "msgtype": ev.get("content", {}).get("msgtype"),
                    }
                )
        return messages, data.get("end", "")

    async def sync(self, timeout: int = 1000, since: Optional[str] = None) -> dict:
        params: dict[str, Any] = {"timeout": timeout}
        if since:
            params["since"] = since
        r = await self._http.get("/_matrix/client/v3/sync", params=params)
        r.raise_for_status()
        return r.json()

    async def resolve_room_alias(self, alias: str) -> Optional[str]:
        try:
            r = await self._http.get(f"/_matrix/client/v3/directory/room/{quote(alias, safe='')}")
            if r.status_code == 200:
                return r.json().get("room_id")
        except Exception:
            pass
        return None


_OBSERVER_USERNAME = "test-observer"
_DEFAULT_OBSERVER_PASSWORDS = ("agent-e2e-pass", "observer123")


def _observer_password_candidates() -> tuple[str, ...]:
    """Passwords to try for the shared test-observer account."""
    env_pw = os.environ.get("MATRIX_OBSERVER_PASSWORD", "").strip()
    if env_pw:
        return (env_pw, *_DEFAULT_OBSERVER_PASSWORDS)
    return _DEFAULT_OBSERVER_PASSWORDS


async def _login_observer(client: httpx.AsyncClient, homeserver: str, password: str) -> str | None:
    r = await client.post(
        f"{homeserver}/_matrix/client/v3/login",
        json={
            "type": "m.login.password",
            "identifier": {"type": "m.id.user", "user": _OBSERVER_USERNAME},
            "password": password,
        },
    )
    if r.status_code == 200:
        return r.json()["access_token"]
    return None


async def get_observer_token(
    homeserver: str,
    shared_secret: Optional[str] = None,
) -> str:
    """Get or create an observer Matrix account for watching agent interactions.

    Handles the M_USER_IN_USE race: if registration fails because the user
    already exists (e.g., from a prior CI run on the same Synapse volume),
    falls back to password login.

    Lab Synapse may have created ``test-observer`` with ``observer123``;
    compose/bootstrap uses ``agent-e2e-pass``. Both are tried before
    attempting registration via the shared secret.
    """
    async with httpx.AsyncClient(timeout=30.0) as client:
        for password in _observer_password_candidates():
            token = await _login_observer(client, homeserver, password)
            if token:
                return token

        secret = shared_secret or os.environ.get("MATRIX_SHARED_SECRET", "")
        if not secret:
            raise RuntimeError("Cannot create observer: MATRIX_SHARED_SECRET not set and login failed")

        register_password = _observer_password_candidates()[0]
        nonce_resp = await client.get(f"{homeserver}/_synapse/admin/v1/register")
        nonce = nonce_resp.json()["nonce"]

        mac = hmac.new(secret.encode(), digestmod=hashlib.sha1)
        mac.update(nonce.encode())
        mac.update(b"\x00")
        mac.update(_OBSERVER_USERNAME.encode())
        mac.update(b"\x00")
        mac.update(register_password.encode())
        mac.update(b"\x00")
        mac.update(b"notadmin")

        reg_resp = await client.post(
            f"{homeserver}/_synapse/admin/v1/register",
            json={
                "nonce": nonce,
                "username": _OBSERVER_USERNAME,
                "password": register_password,
                "admin": False,
                "mac": mac.hexdigest(),
            },
        )
        if reg_resp.status_code in (200, 201):
            return reg_resp.json()["access_token"]

        reg_body = reg_resp.json() if reg_resp.headers.get("content-type", "").startswith("application/json") else {}
        if reg_body.get("errcode") == "M_USER_IN_USE":
            log.info("Observer user already exists — retrying login")
            for password in _observer_password_candidates():
                token = await _login_observer(client, homeserver, password)
                if token:
                    return token
            raise RuntimeError("Observer exists but login failed with all known passwords")

        raise RuntimeError(f"Observer registration failed: {reg_resp.status_code} {reg_resp.text}")


async def _synapse_admin_token(
    client: httpx.AsyncClient,
    homeserver: str,
    secret: str,
) -> tuple[str, str]:
    """Register a throwaway Synapse admin user and return (access_token, server_name).

    The registration response's ``home_server`` field gives us the canonical
    server name without needing a separate discovery call.
    """
    nonce_resp = await client.get(f"{homeserver}/_synapse/admin/v1/register")
    nonce_resp.raise_for_status()
    nonce = nonce_resp.json()["nonce"]

    username = f"e2e-admin-{uuid.uuid4().hex[:8]}"
    password = uuid.uuid4().hex

    mac = hmac.new(secret.encode(), digestmod=hashlib.sha1)
    for part in (nonce, "\x00", username, "\x00", password, "\x00", "admin"):
        mac.update(part.encode())

    reg_resp = await client.post(
        f"{homeserver}/_synapse/admin/v1/register",
        json={
            "nonce": nonce,
            "username": username,
            "password": password,
            "admin": True,
            "mac": mac.hexdigest(),
        },
    )
    reg_resp.raise_for_status()
    body = reg_resp.json()
    return body["access_token"], body["home_server"]


async def get_agent_token(
    homeserver: str,
    agent_id: str,
    *,
    shared_secret: Optional[str] = None,
) -> str:
    """Return a Matrix access token for *agent_id* via the Synapse admin API.

    Uses the shared secret to mint a throwaway admin user, then calls the
    admin impersonation endpoint to get a token for the named agent without
    knowing the agent's password. The throwaway admin account is left in
    place — Synapse treats it as an ordinary (low-privilege) account once
    the registration flow completes, and it is never used again.
    """
    secret = shared_secret or os.environ.get("MATRIX_SHARED_SECRET", "")
    if not secret:
        raise RuntimeError(
            "MATRIX_SHARED_SECRET not set — cannot provision agent token via admin API"
        )

    async with httpx.AsyncClient(timeout=30.0) as client:
        admin_token, server_name = await _synapse_admin_token(client, homeserver, secret)
        user_id = f"@{agent_id}:{server_name}"
        resp = await client.post(
            f"{homeserver}/_synapse/admin/v1/users/{user_id}/login",
            headers={"Authorization": f"Bearer {admin_token}"},
            json={},
        )
        resp.raise_for_status()
        return resp.json()["access_token"]


def check_matrix_reachable(base_url: str) -> bool:
    """Synchronous check for Matrix availability."""
    import urllib.error
    import urllib.request

    try:
        with urllib.request.urlopen(f"{base_url}/_matrix/client/versions", timeout=5) as resp:
            return resp.status == 200
    except Exception:
        return False
