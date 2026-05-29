#!/usr/bin/env python3
"""
Usage examples for the Matrix MCP server (tools/matrix-mcp-server).

These examples show how to use the MCP server's Matrix client directly
from Python — useful for interactive debugging, scripting manual test
triggers, and inspecting Matrix room state outside of the pyATS harness.

The MCP client mirrors the patterns established in the older pytest-based
test suite at mycelium_e2e/matrix_e2e.py, which contains full end-to-end
examples of:
    - User registration via Synapse admin API (HMAC shared-secret flow)
    - Room creation, agent join, and multi-agent negotiation orchestration
    - Matrix ↔ Mycelium coordination with IOC path verification
    - Cleanup of Matrix rooms and Mycelium sessions

The pyATS test suite (testcases/matrix_tests.py) uses libs/matrix_client.py,
which is a near-identical async httpx wrapper. The MCP client adds a few
extra operations (reactions, room listing, member inspection) and is the
preferred entrypoint for Cursor agents and interactive debugging.

Prerequisites:
    - Matrix Synapse running (docker compose -f infra/compose.e2e.yaml up -d)
    - A valid access token (see tools/matrix-mcp-server/README.md)

Run a single example:
    uv run python tests/examples_matrix_mcp.py whoami
    uv run python tests/examples_matrix_mcp.py send --room '#agents:local' --body 'hello from script'
    uv run python tests/examples_matrix_mcp.py read --room '#agents:local'
    uv run python tests/examples_matrix_mcp.py roundtrip
    uv run python tests/examples_matrix_mcp.py register --user test-agent --password agent123
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import hmac
import json
import os
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools" / "matrix-mcp-server" / "src"))

import httpx  # noqa: E402
from matrix_mcp.matrix_client import MatrixClient  # noqa: E402

MATRIX_HOMESERVER = os.environ.get("MATRIX_HOMESERVER", "http://localhost:8008")
MATRIX_SHARED_SECRET = os.environ.get("MATRIX_SHARED_SECRET", "")


def _get_client() -> MatrixClient:
    homeserver = os.environ.get("MATRIX_HOMESERVER", "http://localhost:8008")
    token = os.environ.get("MATRIX_ACCESS_TOKEN", "")
    if not token:
        print(
            "Set MATRIX_ACCESS_TOKEN in your environment.\n"
            "See tools/matrix-mcp-server/README.md for how to obtain one.",
            file=sys.stderr,
        )
        sys.exit(1)
    return MatrixClient(homeserver=homeserver, access_token=token)


# -- Example: whoami ---------------------------------------------------------

async def example_whoami() -> None:
    """Verify the token is valid by checking the authenticated user ID."""
    client = _get_client()
    try:
        result = await client.whoami()
        print(json.dumps(result, indent=2))
    finally:
        await client.close()


# -- Example: resolve alias --------------------------------------------------

async def example_resolve(alias: str) -> None:
    """Resolve a room alias like #agents:local to its room ID."""
    client = _get_client()
    try:
        result = await client.resolve_alias(alias)
        print(json.dumps(result, indent=2))
    finally:
        await client.close()


# -- Example: send message ---------------------------------------------------

async def example_send(room: str, body: str) -> None:
    """Send a text message to a room (by ID or alias)."""
    client = _get_client()
    try:
        result = await client.send_message(room, body)
        print(json.dumps(result, indent=2))
    finally:
        await client.close()


# -- Example: read messages --------------------------------------------------

async def example_read(room: str, limit: int = 10) -> None:
    """Read recent messages from a room."""
    client = _get_client()
    try:
        messages = await client.read_messages(room, limit=limit)
        for msg in messages:
            sender = msg.get("sender", "?")
            body = msg.get("body", "")
            print(f"  {sender}: {body}")
        print(f"\n({len(messages)} messages)")
    finally:
        await client.close()


# -- Example: full round-trip ------------------------------------------------

async def example_roundtrip() -> None:
    """Send a unique marker message and verify it appears in the read-back.

    This mirrors the pattern used by testcases/matrix_tests.py::MatrixCommunication
    but via the MCP client rather than libs/matrix_client.py.
    """
    client = _get_client()
    marker = f"mcp-example-{uuid.uuid4().hex[:8]}"
    try:
        alias = "#agents:local"
        resolved = await client.resolve_alias(alias)
        room_id = resolved["room_id"]
        print(f"Resolved {alias} -> {room_id}")

        await client.join_room(room_id)
        print(f"Joined {room_id}")

        await client.send_message(room_id, f"[mcp-example] ping {marker}")
        print(f"Sent marker: {marker}")

        messages = await client.read_messages(room_id, limit=10)
        found = any(marker in (m.get("body") or "") for m in messages)
        if found:
            print(f"Round-trip OK: marker found in {len(messages)} messages")
        else:
            print(f"FAIL: marker not found in {len(messages)} messages", file=sys.stderr)
            sys.exit(1)
    finally:
        await client.close()


# -- Example: list rooms -----------------------------------------------------

async def example_list_rooms() -> None:
    """List all rooms the authenticated user has joined."""
    client = _get_client()
    try:
        rooms = await client.list_rooms()
        for room in rooms:
            print(f"  {room['room_id']}  {room.get('name', '(unnamed)')}")
        print(f"\n({len(rooms)} rooms)")
    finally:
        await client.close()


# -- Example: room members ---------------------------------------------------

async def example_members(room: str) -> None:
    """List members of a room."""
    client = _get_client()
    try:
        members = await client.get_room_members(room)
        for m in members:
            print(f"  {m['user_id']}  ({m.get('display_name', '-')})")
        print(f"\n({len(members)} members)")
    finally:
        await client.close()


# -- Example: create room + invite -------------------------------------------

async def example_create_room(name: str, invite: list[str] | None = None) -> None:
    """Create a private room and optionally invite users."""
    client = _get_client()
    try:
        result = await client.create_room(name, invite=invite)
        print(json.dumps(result, indent=2))
    finally:
        await client.close()


# -- Example: trigger negotiation (manual test helper) -----------------------

async def example_trigger_negotiation(
    room: str,
    topic: str = "Sprint planning for Q3 release",
    agents: str = "agent-alpha,agent-beta",
) -> None:
    """Send a negotiation trigger message to a Matrix room.

    This is the manual equivalent of what distributed_tests.py does: it posts
    a message to the #agents:local room (or a specific room) that the OpenClaw
    agents' mycelium-room channel plugin picks up as a negotiation trigger.

    Useful for ad-hoc testing of the agent trigger → join → negotiate pipeline
    without running the full pyATS suite.
    """
    agent_list = [a.strip() for a in agents.split(",")]
    trigger = (
        f"@all Please coordinate on: {topic}\n"
        f"Participants: {', '.join(agent_list)}\n"
        f"Room: negotiation-{uuid.uuid4().hex[:8]}"
    )
    client = _get_client()
    try:
        result = await client.send_message(room, trigger)
        print(f"Trigger sent: event_id={result.get('event_id')}")
        print(f"  topic: {topic}")
        print(f"  agents: {agent_list}")
    finally:
        await client.close()


# -- Example: register user (from mycelium_e2e/matrix_e2e.py) ----------------

async def example_register(username: str, password: str, admin: bool = False) -> None:
    """Register a Matrix user via the Synapse shared-secret admin API.

    This mirrors the pattern from mycelium_e2e/matrix_e2e.py::register_matrix_user.
    Tries login first; falls back to HMAC-based registration if login fails.
    Requires MATRIX_SHARED_SECRET to be set for new registrations.
    """
    async with httpx.AsyncClient(timeout=30.0) as client:
        r = await client.post(
            f"{MATRIX_HOMESERVER}/_matrix/client/v3/login",
            json={"type": "m.login.password", "user": username, "password": password},
        )
        if r.status_code == 200:
            data = r.json()
            print(f"Logged in as existing user: {data.get('user_id')}")
            print(f"Access token: {data['access_token']}")
            return

        if not MATRIX_SHARED_SECRET:
            print(
                "User does not exist and MATRIX_SHARED_SECRET is not set.\n"
                "Set it to register new users (check infra/synapse/homeserver.yaml).",
                file=sys.stderr,
            )
            sys.exit(1)

        nonce_resp = await client.get(f"{MATRIX_HOMESERVER}/_synapse/admin/v1/register")
        nonce = nonce_resp.json()["nonce"]

        mac = hmac.new(MATRIX_SHARED_SECRET.encode(), digestmod=hashlib.sha1)
        mac.update(nonce.encode())
        mac.update(b"\x00")
        mac.update(username.encode())
        mac.update(b"\x00")
        mac.update(password.encode())
        mac.update(b"\x00")
        mac.update(b"admin" if admin else b"notadmin")

        reg_resp = await client.post(
            f"{MATRIX_HOMESERVER}/_synapse/admin/v1/register",
            json={
                "nonce": nonce,
                "username": username,
                "password": password,
                "admin": admin,
                "mac": mac.hexdigest(),
            },
        )
        if reg_resp.status_code in (200, 201):
            data = reg_resp.json()
            print(f"Registered: {data.get('user_id')}")
            print(f"Access token: {data['access_token']}")
        else:
            print(f"Registration failed: {reg_resp.status_code} {reg_resp.text}", file=sys.stderr)
            sys.exit(1)


# -- Example: multi-agent setup (from mycelium_e2e/matrix_e2e.py) -----------

async def example_multi_agent_setup(
    room_name: str = "mcp-demo",
    agents: str = "agent-alpha,agent-beta",
) -> None:
    """Create a Matrix room, register agents, and have them join.

    Demonstrates the full setup flow from mycelium_e2e/matrix_e2e.py::setup_matrix_e2e_test
    using the MCP client. Useful as a starting point for scripted negotiation tests.
    """
    if not MATRIX_SHARED_SECRET:
        print("MATRIX_SHARED_SECRET required for agent registration", file=sys.stderr)
        sys.exit(1)

    agent_list = [a.strip() for a in agents.split(",")]

    async with httpx.AsyncClient(timeout=30.0) as http:
        admin_r = await http.post(
            f"{MATRIX_HOMESERVER}/_matrix/client/v3/login",
            json={"type": "m.login.password", "user": "e2e-admin", "password": "admin123"},
        )
        if admin_r.status_code != 200:
            print("Admin login failed -- register e2e-admin first via 'register' command", file=sys.stderr)
            sys.exit(1)
        admin_token = admin_r.json()["access_token"]

    admin = MatrixClient(homeserver=MATRIX_HOMESERVER, access_token=admin_token)
    try:
        alias = f"mcp-{room_name}-{uuid.uuid4().hex[:6]}"
        room = await admin.create_room(room_name, alias=alias)
        room_id = room["room_id"]
        print(f"Created room: #{alias}:local  ({room_id})")

        for handle in agent_list:
            await example_register(handle, f"{handle}-pass")
            async with httpx.AsyncClient(timeout=30.0) as http:
                login_r = await http.post(
                    f"{MATRIX_HOMESERVER}/_matrix/client/v3/login",
                    json={"type": "m.login.password", "user": handle, "password": f"{handle}-pass"},
                )
                agent_token = login_r.json()["access_token"]
            agent_client = MatrixClient(homeserver=MATRIX_HOMESERVER, access_token=agent_token)
            await agent_client.join_room(room_id)
            await agent_client.close()
            print(f"  {handle} joined")

        members = await admin.get_room_members(room_id)
        print(f"\nRoom has {len(members)} members:")
        for m in members:
            print(f"  {m['user_id']}")
    finally:
        await admin.close()


# -- CLI dispatch ------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Matrix MCP client usage examples",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("whoami", help="Check authenticated identity")

    p = sub.add_parser("resolve", help="Resolve a room alias")
    p.add_argument("--alias", default="#agents:local")

    p = sub.add_parser("send", help="Send a message")
    p.add_argument("--room", required=True)
    p.add_argument("--body", required=True)

    p = sub.add_parser("read", help="Read recent messages")
    p.add_argument("--room", required=True)
    p.add_argument("--limit", type=int, default=10)

    sub.add_parser("roundtrip", help="Send+read verification")
    sub.add_parser("rooms", help="List joined rooms")

    p = sub.add_parser("members", help="List room members")
    p.add_argument("--room", required=True)

    p = sub.add_parser("create", help="Create a room")
    p.add_argument("--name", required=True)
    p.add_argument("--invite", nargs="*", help="User IDs to invite")

    p = sub.add_parser("trigger", help="Send a negotiation trigger")
    p.add_argument("--room", default="#agents:local")
    p.add_argument("--topic", default="Sprint planning for Q3 release")
    p.add_argument("--agents", default="agent-alpha,agent-beta")

    p = sub.add_parser("register", help="Register a Matrix user (HMAC admin API)")
    p.add_argument("--user", required=True)
    p.add_argument("--password", required=True)
    p.add_argument("--admin", action="store_true")

    p = sub.add_parser("setup", help="Create room + register + join agents")
    p.add_argument("--room", default="mcp-demo")
    p.add_argument("--agents", default="agent-alpha,agent-beta")

    args = parser.parse_args()

    dispatch = {
        "whoami": lambda: example_whoami(),
        "resolve": lambda: example_resolve(args.alias),
        "send": lambda: example_send(args.room, args.body),
        "read": lambda: example_read(args.room, args.limit),
        "roundtrip": lambda: example_roundtrip(),
        "rooms": lambda: example_list_rooms(),
        "members": lambda: example_members(args.room),
        "create": lambda: example_create_room(args.name, args.invite),
        "trigger": lambda: example_trigger_negotiation(args.room, args.topic, args.agents),
        "register": lambda: example_register(args.user, args.password, args.admin),
        "setup": lambda: example_multi_agent_setup(args.room, args.agents),
    }

    asyncio.run(dispatch[args.command]())


if __name__ == "__main__":
    main()
