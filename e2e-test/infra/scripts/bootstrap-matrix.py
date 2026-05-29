#!/usr/bin/env python3
"""Bootstrap Matrix Synapse for E2E tests.

Creates agent accounts, a shared room, and exports tokens to /shared/matrix-tokens.json
so other containers and the host test runner can authenticate.
"""

import hashlib
import hmac
import json
import os
import sys
import time
import urllib.error
import urllib.request

HOMESERVER = os.environ.get("MATRIX_HOMESERVER", "http://matrix-synapse:8008")
SHARED_SECRET = os.environ.get("MATRIX_SHARED_SECRET", "e2e-shared-secret")
TOKEN_OUTPUT = os.environ.get("TOKEN_OUTPUT", "/shared/matrix-tokens.json")

AGENTS = [
    "agent-alpha",
    "agent-beta",
    "agent-gamma",
    "agent-delta",
    "claire-agent",
    "oclw5-agent",
    "test-observer",
]

ROOM_ALIAS = "agents"


def _request(method, url, data=None, token=None, timeout=15):
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    body = json.dumps(data).encode() if data else None
    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        body_text = e.read().decode() if e.fp else ""
        try:
            return e.code, json.loads(body_text)
        except json.JSONDecodeError:
            return e.code, {"error": body_text}


def wait_for_synapse(max_wait=60):
    deadline = time.time() + max_wait
    while time.time() < deadline:
        try:
            req = urllib.request.Request(f"{HOMESERVER}/_matrix/client/versions")
            with urllib.request.urlopen(req, timeout=5):
                print("Synapse is ready")
                return
        except Exception:
            time.sleep(1)
    print("ERROR: Synapse did not become ready", file=sys.stderr)
    sys.exit(1)


def register_user(username, password="agent-e2e-pass", admin=False):
    """Register a user via the shared-secret admin API."""
    status, nonce_data = _request("GET", f"{HOMESERVER}/_synapse/admin/v1/register")
    if status != 200:
        print(f"  Failed to get nonce: {status} {nonce_data}", file=sys.stderr)
        return None

    nonce = nonce_data["nonce"]
    mac = hmac.new(SHARED_SECRET.encode(), digestmod=hashlib.sha1)
    mac.update(nonce.encode())
    mac.update(b"\x00")
    mac.update(username.encode())
    mac.update(b"\x00")
    mac.update(password.encode())
    mac.update(b"\x00")
    mac.update(b"admin" if admin else b"notadmin")

    status, result = _request("POST", f"{HOMESERVER}/_synapse/admin/v1/register", {
        "nonce": nonce,
        "username": username,
        "password": password,
        "admin": admin,
        "mac": mac.hexdigest(),
    })

    if status in (200, 201):
        print(f"  Registered @{username}:local")
        return result.get("access_token")

    if "User ID already taken" in str(result.get("error", "")):
        print(f"  @{username}:local already exists, logging in...")
        status, login_result = _request("POST", f"{HOMESERVER}/_matrix/client/v3/login", {
            "type": "m.login.password",
            "user": username,
            "password": password,
        })
        if status == 200:
            return login_result.get("access_token")
        print(f"  Login failed: {status} {login_result}", file=sys.stderr)
        return None

    print(f"  Registration failed: {status} {result}", file=sys.stderr)
    return None


def create_room(token, alias):
    """Create a room with the given alias and return the room_id."""
    status, result = _request("POST", f"{HOMESERVER}/_matrix/client/v3/createRoom", {
        "room_alias_name": alias,
        "visibility": "public",
        "preset": "public_chat",
        "name": f"#{alias}:local",
    }, token=token)

    if status == 200:
        room_id = result.get("room_id")
        print(f"  Created room #{alias}:local -> {room_id}")
        return room_id

    if "already in use" in str(result.get("error", "")).lower():
        status, resolve = _request(
            "GET",
            f"{HOMESERVER}/_matrix/client/v3/directory/room/%23{alias}%3Alocal",
            token=token,
        )
        if status == 200:
            room_id = resolve.get("room_id")
            print(f"  Room #{alias}:local already exists -> {room_id}")
            return room_id

    print(f"  Room creation failed: {status} {result}", file=sys.stderr)
    return None


def invite_and_join(room_id, inviter_token, invitee_user_id, invitee_token):
    """Invite a user to a room and have them join."""
    _request("POST", f"{HOMESERVER}/_matrix/client/v3/rooms/{room_id}/invite",
             {"user_id": invitee_user_id}, token=inviter_token)
    _request("POST", f"{HOMESERVER}/_matrix/client/v3/rooms/{room_id}/join",
             {}, token=invitee_token)


def main():
    wait_for_synapse()

    print("\nRegistering agent accounts...")
    tokens = {}
    for agent in AGENTS:
        token = register_user(agent)
        if token:
            tokens[agent] = token
        else:
            print(f"  WARNING: Could not register {agent}", file=sys.stderr)

    if not tokens:
        print("ERROR: No agents registered", file=sys.stderr)
        sys.exit(1)

    admin_agent = next(iter(tokens))
    admin_token = tokens[admin_agent]

    print(f"\nCreating room #{ROOM_ALIAS}:local...")
    room_id = create_room(admin_token, ROOM_ALIAS)

    if room_id:
        print("\nJoining all agents to room...")
        for agent, token in tokens.items():
            if agent == admin_agent:
                continue
            invite_and_join(room_id, admin_token, f"@{agent}:local", token)
            print(f"  @{agent}:local joined")

    output = {
        "homeserver": HOMESERVER,
        "tokens": tokens,
        "room_id": room_id,
        "room_alias": f"#{ROOM_ALIAS}:local",
    }

    os.makedirs(os.path.dirname(TOKEN_OUTPUT), exist_ok=True)
    with open(TOKEN_OUTPUT, "w") as f:
        json.dump(output, f, indent=2)
    print(f"\nTokens written to {TOKEN_OUTPUT}")

    host_output = output.copy()
    host_output["homeserver"] = f"http://localhost:{os.environ.get('E2E_MATRIX_PORT', '8008')}"
    print("\n--- Host-side token summary ---")
    print(json.dumps(host_output, indent=2))
    print("--- end ---")


if __name__ == "__main__":
    main()
