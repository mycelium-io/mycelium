"""Async Matrix client for E2E test interactions."""

from __future__ import annotations

import hashlib
import hmac
import json
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
    ) -> dict:
        txn_id = uuid.uuid4().hex
        payload: dict[str, Any] = {"msgtype": msgtype, "body": body}
        if formatted_body:
            payload["format"] = "org.matrix.custom.html"
            payload["formatted_body"] = formatted_body
        r = await self._http.put(
            f"/_matrix/client/v3/rooms/{quote(room_id, safe='')}/send/m.room.message/{txn_id}",
            json=payload,
        )
        r.raise_for_status()
        return r.json()

    async def read_messages(
        self, room_id: str, limit: int = 50, since: Optional[str] = None
    ) -> tuple[list[dict], str]:
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
                messages.append({
                    "event_id": ev.get("event_id"),
                    "sender": ev.get("sender"),
                    "timestamp": ev.get("origin_server_ts"),
                    "body": ev.get("content", {}).get("body", ""),
                    "msgtype": ev.get("content", {}).get("msgtype"),
                })
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
            r = await self._http.get(
                f"/_matrix/client/v3/directory/room/{quote(alias, safe='')}"
            )
            if r.status_code == 200:
                return r.json().get("room_id")
        except Exception:
            pass
        return None


_OBSERVER_USERNAME = "test-observer"
_OBSERVER_PASSWORD = "agent-e2e-pass"


async def get_observer_token(
    homeserver: str,
    shared_secret: Optional[str] = None,
) -> str:
    """Get or create an observer Matrix account for watching agent interactions.

    Handles the M_USER_IN_USE race: if registration fails because the user
    already exists (e.g., from a prior CI run on the same Synapse volume),
    falls back to password login.

    The password must match what ``bootstrap-matrix.py`` uses for all agent
    accounts (``agent-e2e-pass``).
    """
    async with httpx.AsyncClient(timeout=30.0) as client:
        r = await client.post(
            f"{homeserver}/_matrix/client/v3/login",
            json={
                "type": "m.login.password",
                "identifier": {"type": "m.id.user", "user": _OBSERVER_USERNAME},
                "password": _OBSERVER_PASSWORD,
            },
        )
        if r.status_code == 200:
            return r.json()["access_token"]

        secret = shared_secret or os.environ.get("MATRIX_SHARED_SECRET", "")
        if not secret:
            raise RuntimeError("Cannot create observer: MATRIX_SHARED_SECRET not set and login failed")

        nonce_resp = await client.get(f"{homeserver}/_synapse/admin/v1/register")
        nonce = nonce_resp.json()["nonce"]

        mac = hmac.new(secret.encode(), digestmod=hashlib.sha1)
        mac.update(nonce.encode())
        mac.update(b"\x00")
        mac.update(_OBSERVER_USERNAME.encode())
        mac.update(b"\x00")
        mac.update(_OBSERVER_PASSWORD.encode())
        mac.update(b"\x00")
        mac.update(b"notadmin")

        reg_resp = await client.post(
            f"{homeserver}/_synapse/admin/v1/register",
            json={
                "nonce": nonce,
                "username": _OBSERVER_USERNAME,
                "password": _OBSERVER_PASSWORD,
                "admin": False,
                "mac": mac.hexdigest(),
            },
        )
        if reg_resp.status_code in (200, 201):
            return reg_resp.json()["access_token"]

        reg_body = reg_resp.json() if reg_resp.headers.get("content-type", "").startswith("application/json") else {}
        if reg_body.get("errcode") == "M_USER_IN_USE":
            log.info("Observer user already exists — retrying login")
            retry = await client.post(
                f"{homeserver}/_matrix/client/v3/login",
                json={
                    "type": "m.login.password",
                    "identifier": {"type": "m.id.user", "user": _OBSERVER_USERNAME},
                    "password": _OBSERVER_PASSWORD,
                },
            )
            if retry.status_code == 200:
                return retry.json()["access_token"]
            raise RuntimeError(
                f"Observer exists but login failed: {retry.status_code} {retry.text}"
            )

        raise RuntimeError(f"Observer registration failed: {reg_resp.status_code} {reg_resp.text}")


def check_matrix_reachable(base_url: str) -> bool:
    """Synchronous check for Matrix availability."""
    import urllib.request
    import urllib.error

    try:
        with urllib.request.urlopen(f"{base_url}/_matrix/client/versions", timeout=5) as resp:
            return resp.status == 200
    except Exception:
        return False
