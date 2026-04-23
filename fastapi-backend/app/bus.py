# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cisco Systems, Inc. and its affiliates

"""
Async Postgres LISTEN/NOTIFY bus.

Thin wrapper over asyncpg for room-scoped pub/sub.
Channel naming convention: "room:{room_name}"
"""

import json
import logging
from collections.abc import Callable

import asyncpg

logger = logging.getLogger(__name__)


def room_channel(room_name: str) -> str:
    """Canonical channel name for a room."""
    return f"room:{room_name}"


def agent_channel(handle: str) -> str:
    """Canonical channel name for per-agent push notifications."""
    return f"agent:{handle}"


_NOTIFY_MAX_BYTES = 7000  # Postgres hard limit is 8000; stay well under


async def notify(conn: asyncpg.Connection, channel: str, payload: dict) -> None:
    """Publish a payload to a Postgres NOTIFY channel.

    If the serialized payload exceeds the Postgres 8KB NOTIFY limit, falls back
    to a slim ping containing only the message ID and metadata so the SSE
    consumer can fetch the full content from the database.
    """
    raw = json.dumps(payload)
    if len(raw.encode()) > _NOTIFY_MAX_BYTES and "id" in payload:
        raw = json.dumps(
            {
                "id": payload["id"],
                "room_name": payload.get("room_name"),
                "sender_handle": payload.get("sender_handle"),
                "message_type": payload.get("message_type"),
                "created_at": payload.get("created_at"),
                "_slim": True,
            }
        )
    await conn.execute("SELECT pg_notify($1, $2)", channel, raw)


async def listen(
    conn: asyncpg.Connection,
    channel: str,
    callback: Callable,
) -> None:
    """
    Register a listener on a Postgres LISTEN channel.

    The callback receives (conn, pid, channel, payload_str).
    """
    await conn.add_listener(channel, callback)
    await conn.execute(f"LISTEN {asyncpg.utils._quote_ident(channel)}")
    logger.debug(f"Listening on channel: {channel}")


async def unlisten(conn: asyncpg.Connection, channel: str) -> None:
    """Unregister listener and stop listening on a channel."""
    try:
        await conn.execute(f"UNLISTEN {asyncpg.utils._quote_ident(channel)}")
        await conn.remove_listener(channel, None)  # type: ignore[arg-type]
    except Exception as e:
        logger.debug(f"unlisten error on {channel}: {e}")
