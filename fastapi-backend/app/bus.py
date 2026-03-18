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


async def notify(conn: asyncpg.Connection, channel: str, payload: dict) -> None:
    """Publish a payload to a Postgres NOTIFY channel."""
    await conn.execute("SELECT pg_notify($1, $2)", channel, json.dumps(payload))


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
