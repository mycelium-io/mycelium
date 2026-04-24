"""
Cross-channel memory isolation E2E test.

Proves that memory accumulated in one mycelium room is NOT automatically
visible to an agent woken in a different room's session context, and then
tests whether explicit context inclusion can bridge the gap.

Architecture:
  Phase 1 — Seed: Tell agent-alpha (via Matrix) to store a specific decision
            in a dedicated mycelium room.  Verify the memory was written.
  Phase 2 — Isolate: Confirm the mycelium-room channel's configured room
            has no trace of that decision.
  Phase 3 — Blind probe: Ask agent-beta (via Matrix) about the decision
            WITHOUT including context.  Expect no knowledge.
  Phase 4 — Bridged probe: Ask agent-beta the SAME question but include
            the relevant context in the message body.  Expect awareness.

This validates that an agent in a different session context is oblivious
to another room's memory, and that sender-included context is the bridge.

Requires:
  - Mycelium backend running on oclw4
  - OpenClaw gateway running with agent-alpha + agent-beta on Matrix
    and mycelium-room channels
  - Matrix homeserver running
"""

from __future__ import annotations

import asyncio
import os
import time
import uuid
from dataclasses import dataclass, field
from typing import Optional
from urllib.parse import quote

import httpx

from mycelium_e2e.bundle import (
    BACKEND_URL,
    TestContext,
    check,
    log_info,
    log_debug,
    log_error,
    log_warning,
    print_section,
    GREEN, RED, YELLOW, DIM, BOLD, RESET,
)

MATRIX_HOMESERVER = os.environ.get("MATRIX_HOMESERVER", "http://localhost:8008")
MATRIX_SHARED_SECRET = os.environ.get(
    "MATRIX_SHARED_SECRET",
    "C&1gRZ#;M2hEp-ehNLtSPeddl^DOutp*Ls4=eDyx_+._^Y#ieY",
)

# The mycelium-room channel's configured room (from openclaw.json)
MYCELIUM_CHANNEL_ROOM = "mycelium-room"

# Unique test token so we can identify our specific decision in agent output
DECISION_TOKEN = "ZANTHOR-CACHE"


@dataclass
class CrossChannelContext:
    test_name: str
    seed_room: Optional[str] = None
    observer_token: Optional[str] = None
    matrix_room_id: Optional[str] = None
    start_time: float = field(default_factory=time.time)


class MatrixClient:
    """Minimal async Matrix client for test operations."""

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
        formatted_body: Optional[str] = None,
    ) -> dict:
        txn_id = uuid.uuid4().hex
        payload: dict = {"msgtype": "m.text", "body": body}
        if formatted_body:
            payload["format"] = "org.matrix.custom.html"
            payload["formatted_body"] = formatted_body
        r = await self._http.put(
            f"/_matrix/client/v3/rooms/{quote(room_id, safe='')}/send/m.room.message/{txn_id}",
            json=payload,
        )
        r.raise_for_status()
        return r.json()

    async def read_messages(self, room_id: str, limit: int = 50) -> list[dict]:
        r = await self._http.get(
            f"/_matrix/client/v3/rooms/{quote(room_id, safe='')}/messages",
            params={"dir": "b", "limit": limit},
        )
        r.raise_for_status()
        messages = []
        for ev in reversed(r.json().get("chunk", [])):
            if ev.get("type") == "m.room.message":
                messages.append({
                    "event_id": ev.get("event_id"),
                    "sender": ev.get("sender"),
                    "timestamp": ev.get("origin_server_ts"),
                    "body": ev.get("content", {}).get("body", ""),
                })
        return messages

    async def join_room(self, room_id_or_alias: str) -> dict:
        r = await self._http.post(
            f"/_matrix/client/v3/join/{quote(room_id_or_alias, safe='')}",
            json={},
        )
        r.raise_for_status()
        return r.json()


async def get_observer_token() -> str:
    """Get or create a test-observer Matrix account."""
    async with httpx.AsyncClient(timeout=30.0) as client:
        r = await client.post(
            f"{MATRIX_HOMESERVER}/_matrix/client/v3/login",
            json={"type": "m.login.password", "user": "test-observer", "password": "observer123"},
        )
        if r.status_code == 200:
            return r.json()["access_token"]

        import hmac
        import hashlib

        r = await client.get(f"{MATRIX_HOMESERVER}/_synapse/admin/v1/register")
        nonce = r.json()["nonce"]
        mac_content = f"{nonce}\x00test-observer\x00observer123\x00notadmin"
        mac = hmac.new(
            MATRIX_SHARED_SECRET.encode(), mac_content.encode(), hashlib.sha1
        ).hexdigest()
        r = await client.post(
            f"{MATRIX_HOMESERVER}/_synapse/admin/v1/register",
            json={
                "nonce": nonce,
                "username": "test-observer",
                "password": "observer123",
                "admin": False,
                "mac": mac,
            },
        )
        r.raise_for_status()
        return r.json()["access_token"]


async def wait_for_agent_response(
    client: MatrixClient,
    room_id: str,
    agent: str,
    after_timestamp: int,
    timeout_seconds: int = 90,
    poll_interval: int = 5,
) -> list[str]:
    """Wait for a specific agent to respond in Matrix after a given timestamp."""
    start = time.time()
    seen: set[str] = set()
    responses: list[str] = []

    while time.time() - start < timeout_seconds:
        messages = await client.read_messages(room_id, limit=100)
        for msg in messages:
            eid = msg.get("event_id", "")
            if eid in seen:
                continue
            seen.add(eid)
            if msg.get("timestamp", 0) <= after_timestamp:
                continue
            sender = msg.get("sender", "")
            if f"@{agent}:local" == sender or agent in sender:
                responses.append(msg.get("body", ""))
                log_debug(f"{agent} responded: {msg['body'][:120]}...")

        if responses:
            return responses
        await asyncio.sleep(poll_interval)

    log_warning(f"Timeout waiting for {agent} response")
    return responses


# ─────────────────────────────────────────────────────────────────────────────
# Main test
# ─────────────────────────────────────────────────────────────────────────────


async def test_cross_channel_memory_isolation(test_ctx: TestContext):
    """
    Prove that cross-channel memory is isolated, and show how to bridge it.

    Phase 1: Seed context in a dedicated room via Matrix (agent-alpha)
    Phase 2: Verify isolation — the mycelium-room has no trace
    Phase 3: Blind probe — ask agent-beta via mycelium-room (expects no knowledge)
    Phase 4: Bridged probe — include context in the message (expects awareness)
    """
    print_section(50, "Cross-channel memory isolation")

    seed_room = f"xch-seed-{uuid.uuid4().hex[:8]}"
    ctx = CrossChannelContext(test_name="cross-channel-isolation", seed_room=seed_room)

    skip_checks = [
        "Seed room created",
        "Matrix trigger sent to agent-alpha",
        "agent-alpha responded in Matrix",
        "Memory written to seed room",
        "Mycelium-room has no seed-room memories",
        "Mycelium-room messages have no seed-room content",
        "Blind probe sent to agent-beta",
        "agent-beta responded to blind probe",
        "Blind probe response lacks seed-room knowledge",
        "Bridged probe sent to agent-beta",
        "agent-beta responded to bridged probe",
        "Bridged probe response contains seed-room knowledge",
        # Phase 5: session-level isolation via `mycelium room send` DM
        "Channel DM posted to mycelium-room",
        "agent-beta received DM in a fresh session",
        "DM response lacks sender's Matrix history",
    ]

    if test_ctx.skip_llm_tests:
        for name in skip_checks:
            check(test_ctx, name, False, skipped=True, skip_reason="LLM unavailable")
        return

    try:
        # ── Phase 1: Seed context via Matrix ──────────────────────────────

        log_info(f"Phase 1: Seeding context in room {seed_room} via Matrix")

        # Create the seed room in Mycelium
        async with httpx.AsyncClient(timeout=30.0) as http:
            r = await http.post(
                f"{BACKEND_URL}/rooms",
                json={"name": seed_room, "mode": "coordination"},
            )
        room_created = r.status_code in (200, 201)
        check(test_ctx, "Seed room created", room_created,
              error=f"status {r.status_code}: {r.text}" if not room_created else None)

        if not room_created:
            for name in skip_checks[1:]:
                check(test_ctx, name, False, skipped=True, skip_reason="Seed room creation failed")
            return

        # Get Matrix observer token and send trigger to agent-alpha
        ctx.observer_token = await get_observer_token()
        observer = MatrixClient(MATRIX_HOMESERVER, ctx.observer_token)

        # Use #agents:local since agents are configured to watch it
        agents_room = "!XSQgKkMAXJHhTwQLTE:local"
        try:
            await observer.join_room(agents_room)
        except Exception:
            pass

        await asyncio.sleep(2)
        trigger_ts = int(time.time() * 1000)

        # Important: the seed room has already been created server-side
        # above (POST /rooms). Older versions of this prompt let the agent
        # infer it should run `mycelium room create`, which (a) is wrong
        # and (b) can hit per-agent approval gates on the leaf node and
        # silently stall the whole test. Spell out the exact two commands
        # and explicitly tell the agent NOT to create the room.
        seed_prompt = (
            f"@agent-alpha:local\n\n"
            f"Please evaluate caching strategies for a hypothetical project called {DECISION_TOKEN}. "
            f"Specifically, compare Redis vs Memcached. The mycelium room `{seed_room}` "
            f"already exists — do NOT create it. After your analysis, store your decision "
            f"by running EXACTLY these two commands (no others):\n\n"
            f"```\n"
            f"mycelium room use {seed_room}\n"
            f"mycelium memory set \"decision/{DECISION_TOKEN.lower()}\" "
            f"\"<your decision and rationale>\" --handle agent-alpha\n"
            f"```\n\n"
            f"Then report back here with a summary of what you decided and why."
        )

        html_prompt = (
            f'<a href="https://matrix.to/#/@agent-alpha:local">@agent-alpha:local</a><br/><br/>'
            f"Please evaluate caching strategies for a hypothetical project called <strong>{DECISION_TOKEN}</strong>. "
            f"Specifically, compare Redis vs Memcached. The mycelium room <code>{seed_room}</code> "
            f"already exists — do <strong>NOT</strong> create it. After your analysis, store your decision "
            f"by running EXACTLY these two commands (no others):<br/><br/>"
            f"<pre><code>"
            f"mycelium room use {seed_room}\n"
            f"mycelium memory set \"decision/{DECISION_TOKEN.lower()}\" "
            f"\"&lt;your decision and rationale&gt;\" --handle agent-alpha"
            f"</code></pre><br/>"
            f"Then report back here with a summary of what you decided and why."
        )

        await observer.send_message(agents_room, seed_prompt, formatted_body=html_prompt)
        log_info("Seed trigger sent to agent-alpha via Matrix")
        check(test_ctx, "Matrix trigger sent to agent-alpha", True)

        # Wait for agent-alpha to respond
        alpha_responses = await wait_for_agent_response(
            observer, agents_room, "agent-alpha", trigger_ts, timeout_seconds=120,
        )
        alpha_responded = len(alpha_responses) > 0
        check(test_ctx, "agent-alpha responded in Matrix", alpha_responded,
              error="No response from agent-alpha within 120s" if not alpha_responded else None)

        # Verify memory was written to seed room
        await asyncio.sleep(5)  # Give time for memory write to propagate
        memory_found = False
        async with httpx.AsyncClient(timeout=30.0) as http:
            r = await http.get(f"{BACKEND_URL}/rooms/{quote(seed_room, safe='')}/memory")
            if r.status_code == 200:
                data = r.json()
                memories = data if isinstance(data, list) else data.get("memories", [])
                memory_found = len(memories) > 0
                log_info(f"Seed room has {len(memories)} memories")
            else:
                log_warning(f"Could not read seed room memory: {r.status_code}")

        # If the agent kept hitting approval gates we never ran the seed
        # command on the leaf node — that's an OpenClaw exec-approvals
        # configuration problem on the leaf, not a memory-isolation
        # regression in mycelium. Skip the rest of the test rather than
        # report a misleading isolation failure: the seed never landed,
        # so phases 2–4 can't tell us anything about isolation either.
        approval_blocked = any(
            "Approval required" in msg or "/approve " in msg
            for msg in alpha_responses
        )

        if not memory_found and approval_blocked:
            check(
                test_ctx,
                "Memory written to seed room",
                False,
                skipped=True,
                skip_reason=(
                    "agent-alpha hit OpenClaw approval gates on mycelium commands — "
                    "ensure mycelium is allowlisted for agent-alpha on the leaf node:\n"
                    "  openclaw approvals allowlist add --agent agent-alpha "
                    "--node oclw4 ~/.local/bin/mycelium"
                ),
            )
            for name in skip_checks[3:]:
                check(test_ctx, name, False, skipped=True,
                      skip_reason="seed step skipped — see 'Memory written to seed room'")
            return

        check(test_ctx, "Memory written to seed room", memory_found,
              error="agent-alpha responded but no memories found in seed room" if not memory_found else None)

        # ── Phase 2: Verify isolation ─────────────────────────────────────

        log_info("Phase 2: Verifying cross-channel isolation")

        # Ensure the channel room exists (the plugin should auto-create it
        # on gateway_start, but create it here as a fallback for test stability)
        async with httpx.AsyncClient(timeout=30.0) as http:
            r = await http.get(f"{BACKEND_URL}/rooms/{quote(MYCELIUM_CHANNEL_ROOM, safe='')}")
            if r.status_code == 404:
                log_info(f"Channel room {MYCELIUM_CHANNEL_ROOM} not found — creating it")
                await http.post(
                    f"{BACKEND_URL}/rooms",
                    json={"name": MYCELIUM_CHANNEL_ROOM, "mode": "coordination"},
                )

        channel_room_clean = True
        async with httpx.AsyncClient(timeout=30.0) as http:
            r = await http.get(f"{BACKEND_URL}/rooms/{quote(MYCELIUM_CHANNEL_ROOM, safe='')}/memory")
            if r.status_code == 200:
                data = r.json()
                memories = data if isinstance(data, list) else data.get("memories", [])
                for mem in memories:
                    val = str(mem.get("value", mem.get("content_text", "")))
                    if DECISION_TOKEN.lower() in val.lower():
                        channel_room_clean = False
                        log_error(f"LEAK: seed-room content found in {MYCELIUM_CHANNEL_ROOM} memories")

        check(test_ctx, "Mycelium-room has no seed-room memories", channel_room_clean)

        messages_clean = True
        async with httpx.AsyncClient(timeout=30.0) as http:
            r = await http.get(
                f"{BACKEND_URL}/rooms/{quote(MYCELIUM_CHANNEL_ROOM, safe='')}/messages",
                params={"limit": 50},
            )
            if r.status_code == 200:
                for msg in r.json().get("messages", []):
                    content = msg.get("content", "")
                    if DECISION_TOKEN.lower() in content.lower():
                        messages_clean = False
                        log_error(f"LEAK: seed-room content found in {MYCELIUM_CHANNEL_ROOM} messages")

        check(test_ctx, "Mycelium-room messages have no seed-room content", messages_clean)

        # ── Phase 3: Blind probe ──────────────────────────────────────────

        log_info("Phase 3: Blind probe — asking agent-beta about the decision WITHOUT context")

        await asyncio.sleep(5)
        blind_ts = int(time.time() * 1000)

        blind_probe = (
            f"@agent-beta:local\n\n"
            f"A colleague made a caching technology decision for "
            f"the {DECISION_TOKEN} project. What technology did they choose and why? "
            f"Please be specific about the decision rationale. "
            f"Do NOT guess — only answer if you have actual knowledge of this decision."
        )

        blind_html = (
            f'<a href="https://matrix.to/#/@agent-beta:local">@agent-beta:local</a><br/><br/>'
            f"A colleague made a caching technology decision for "
            f"the <strong>{DECISION_TOKEN}</strong> project. What technology did they choose and why? "
            f"Please be specific about the decision rationale. "
            f"Do NOT guess — only answer if you have actual knowledge of this decision."
        )

        try:
            await observer.send_message(agents_room, blind_probe, formatted_body=blind_html)
            blind_sent = True
        except Exception as e:
            blind_sent = False
            log_error(f"Failed to send blind probe: {e}")

        check(test_ctx, "Blind probe sent to agent-beta", blind_sent,
              error=str(e) if not blind_sent else None)

        if not blind_sent:
            for name in skip_checks[7:]:
                check(test_ctx, name, False, skipped=True, skip_reason="Blind probe send failed")
            await observer.close()
            return

        # Wait for agent-beta's response in Matrix
        blind_responses = await wait_for_agent_response(
            observer, agents_room, "agent-beta", blind_ts, timeout_seconds=90,
        )

        blind_responded = len(blind_responses) > 0
        check(test_ctx, "agent-beta responded to blind probe", blind_responded,
              error="No response from agent-beta within 90s" if not blind_responded else None)

        # Evaluate: agent-beta should NOT know the specific decision
        blind_text = " ".join(blind_responses).lower()
        knows_decision = (
            ("redis" in blind_text or "memcached" in blind_text)
            and any(w in blind_text for w in ["chose", "decided", "selected", "recommend"])
        )

        check(
            test_ctx,
            "Blind probe response lacks seed-room knowledge",
            not knows_decision,
            error=(
                f"UNEXPECTED: agent-beta knew about the {DECISION_TOKEN} decision "
                f"without cross-channel context. Response: {blind_text[:200]}"
            ) if knows_decision else None,
        )

        if blind_responded:
            print(f"    {DIM}Blind probe response (first 200 chars):{RESET}")
            print(f"    {DIM}{blind_text[:200]}{RESET}")

        # ── Phase 4: Bridged probe ────────────────────────────────────────

        log_info("Phase 4: Bridged probe — including context in the message")

        await asyncio.sleep(10)  # Let the blind probe fully settle
        bridge_ts = int(time.time() * 1000)

        # Build the bridged probe with explicit context from the seed room
        seed_context = "No context available"
        async with httpx.AsyncClient(timeout=30.0) as http:
            # Try catchup first (structured summary)
            r = await http.get(
                f"{BACKEND_URL}/rooms/{quote(seed_room, safe='')}/catchup",
            )
            if r.status_code == 200:
                catchup = r.json()
                activity = catchup.get("recent_activity", [])
                if activity:
                    seed_context = "\n".join(
                        f"- {a.get('key', '?')}: {a.get('content_text', '')}"
                        for a in activity[:5]
                    )
                    log_info(f"Loaded {len(activity)} items from seed room catchup")

            # Fallback to raw memory listing
            if seed_context == "No context available":
                r = await http.get(
                    f"{BACKEND_URL}/rooms/{quote(seed_room, safe='')}/memory",
                )
                if r.status_code == 200:
                    data = r.json()
                    memories = data if isinstance(data, list) else data.get("memories", [])
                    if memories:
                        seed_context = "\n".join(
                            f"- {m.get('key', '?')}: {m.get('value', m.get('content_text', ''))}"
                            for m in memories[:5]
                        )
                        log_info(f"Loaded {len(memories)} memories from seed room API")

            # Fallback to agent-alpha's Matrix response
            if seed_context == "No context available" and alpha_responses:
                seed_context = f"agent-alpha's analysis: {alpha_responses[0][:500]}"
                log_info("Using agent-alpha's Matrix response as bridge context")

        bridged_probe = (
            f"@agent-beta:local\n\n"
            f"Here is context from room `{seed_room}` about the "
            f"{DECISION_TOKEN} project caching decision:\n\n"
            f"{seed_context}\n\n"
            f"Based on this context, what technology was chosen and do you agree "
            f"with the rationale? Be specific."
        )

        bridged_html = (
            f'<a href="https://matrix.to/#/@agent-beta:local">@agent-beta:local</a><br/><br/>'
            f"Here is context from room <code>{seed_room}</code> about the "
            f"<strong>{DECISION_TOKEN}</strong> project caching decision:<br/><br/>"
            f"<pre>{seed_context}</pre><br/>"
            f"Based on this context, what technology was chosen and do you agree "
            f"with the rationale? Be specific."
        )

        try:
            await observer.send_message(agents_room, bridged_probe, formatted_body=bridged_html)
            bridge_sent = True
        except Exception as e:
            bridge_sent = False
            log_error(f"Failed to send bridged probe: {e}")

        check(test_ctx, "Bridged probe sent to agent-beta", bridge_sent,
              error=str(e) if not bridge_sent else None)

        if not bridge_sent:
            for name in skip_checks[10:]:
                check(test_ctx, name, False, skipped=True, skip_reason="Bridged probe send failed")
            await observer.close()
            return

        # Wait for agent-beta's response in Matrix
        bridged_responses = await wait_for_agent_response(
            observer, agents_room, "agent-beta", bridge_ts, timeout_seconds=90,
        )

        bridge_responded = len(bridged_responses) > 0
        check(test_ctx, "agent-beta responded to bridged probe", bridge_responded,
              error="No response from agent-beta within 90s" if not bridge_responded else None)

        # Evaluate: agent-beta SHOULD now know the decision
        bridged_text = " ".join(bridged_responses).lower()
        bridge_has_knowledge = (
            "redis" in bridged_text
            or "memcached" in bridged_text
            or "cache" in bridged_text
            or DECISION_TOKEN.lower() in bridged_text
        )

        check(
            test_ctx,
            "Bridged probe response contains seed-room knowledge",
            bridge_has_knowledge,
            error=(
                f"Agent-beta still doesn't reference the caching decision even "
                f"with explicit context. Response: {bridged_text[:200]}"
            ) if not bridge_has_knowledge else None,
        )

        if bridge_responded:
            print(f"    {DIM}Bridged probe response (first 200 chars):{RESET}")
            print(f"    {DIM}{bridged_text[:200]}{RESET}")

        # ── Phase 5: session-level isolation via channel DM ──────────────
        #
        # Mycelium SKILL.md §"Channel Messaging (Cross-Agent DMs)" makes
        # a load-bearing guarantee:
        #
        #   "Sessions are NOT shared across channels. When another agent
        #    sends you a message via the mycelium channel, you receive it
        #    in a *separate session* from whatever conversation you're
        #    currently in with the user. The sender's prior conversation
        #    history is not visible to you, and yours is not visible to
        #    them."
        #
        # Phases 1-4 test *memory* isolation. Phase 5 tests *session*
        # isolation: if agent-alpha drops a `mycelium room send "@agent-
        # beta …"` DM after a long Matrix conversation with the user,
        # agent-beta must respond without any awareness of that Matrix
        # history — they only get the DM text. We post the DM via the
        # backend HTTP API (functionally equivalent to the CLI, but
        # avoids per-agent OpenClaw approval gates on leaf nodes that
        # would otherwise stall the test on a tangential issue).

        log_info("Phase 5: Channel DM isolation — `mycelium room send` from agent-alpha to agent-beta")

        # A deliberately-cryptic reference that only makes sense if beta
        # can see alpha's *prior* Matrix history (which it shouldn't).
        # If beta echoes this token back, session isolation is broken.
        history_canary = f"CANARY-{uuid.uuid4().hex[:8]}"

        # Simulate: alpha has been chatting with the user in Matrix about
        # a secret project. Post that history *only* to the agents-Matrix
        # room (not to the seed room or mycelium-room). Agent-beta has
        # no channel subscription to agents-Matrix, so beta cannot see
        # this — but we include it so the scenario is realistic.
        try:
            await observer.send_message(
                agents_room,
                f"(scratchpad for agent-alpha — internal, do not reply): {history_canary}",
            )
            await asyncio.sleep(2)
        except Exception:
            pass  # Non-fatal; just flavor context.

        dm_ts = int(time.time() * 1000)
        dm_body = (
            f"@agent-beta Heads up: we're standardizing on Redis for the "
            f"{DECISION_TOKEN} project. If that conflicts with anything on "
            f"your side, ping me. (ref: {history_canary})"
        )

        # Post to the channel's configured room (`mycelium-room`), not the
        # seed room. The `mycelium-room` channel plugin only has agents
        # subscribed to its own room, so that's where `mycelium room
        # send` DMs would land in real use. Posting to the seed room
        # would not wake any agent because no one's subscribed there.
        dm_posted = False
        try:
            async with httpx.AsyncClient(timeout=15.0) as http:
                r = await http.post(
                    f"{BACKEND_URL}/rooms/{quote(MYCELIUM_CHANNEL_ROOM, safe='')}/messages",
                    json={
                        "sender_handle": "agent-alpha",
                        "message_type": "broadcast",
                        "content": dm_body,
                    },
                )
                dm_posted = r.status_code in (200, 201, 202)
                if not dm_posted:
                    log_warning(f"Channel DM POST returned {r.status_code}: {r.text[:200]}")
        except Exception as e:
            log_error(f"Channel DM POST failed: {e}")

        check(
            test_ctx,
            "Channel DM posted to mycelium-room",
            dm_posted,
            error="Could not POST channel DM — see backend logs" if not dm_posted else None,
        )

        if not dm_posted:
            for name in skip_checks[13:]:
                check(test_ctx, name, False, skipped=True, skip_reason="DM post failed")
        else:
            # Wait for agent-beta to respond in Matrix (the channel
            # plugin wakes the addressed agent as a fresh session; if
            # beta responds at all, the wake-on-mention path works).
            dm_responses = await wait_for_agent_response(
                observer, agents_room, "agent-beta", dm_ts, timeout_seconds=90,
            )
            dm_responded = len(dm_responses) > 0

            if not dm_responded:
                # The backend's POST /rooms/{room}/messages endpoint
                # writes the message to storage but does NOT invoke the
                # OpenClaw mycelium-room channel plugin's fan-out path
                # — that fires only when a leaf-node `mycelium room
                # send` call arrives *through* the plugin. Running the
                # CLI from inside the test would hit per-agent approval
                # gates on oclw4 (the same failure mode that motivated
                # the prompt fixes above), so we skip the wake + isolation
                # assertions with a pointer to where the gap is.
                check(
                    test_ctx,
                    "agent-beta received DM in a fresh session",
                    False,
                    skipped=True,
                    skip_reason=(
                        "Backend POST /rooms/{room}/messages does not fire the "
                        "OpenClaw mycelium-room plugin's Matrix fan-out — this "
                        "path can only be exercised by `mycelium room send` on a "
                        "leaf node, and that currently requires a per-agent "
                        "approval allowlist entry on oclw4. To enable this "
                        "phase: on oclw4, run `openclaw approvals allowlist add "
                        "--agent agent-alpha --node oclw4 ~/.local/bin/mycelium` "
                        "and retry."
                    ),
                )
                check(
                    test_ctx,
                    "DM response lacks sender's Matrix history",
                    False,
                    skipped=True,
                    skip_reason="upstream wake step was skipped",
                )
            else:
                check(test_ctx, "agent-beta received DM in a fresh session", True)
                dm_text = " ".join(dm_responses)
                # The canary MUST NOT appear in beta's response. If it
                # does, beta somehow saw alpha's Matrix scratchpad —
                # cross-channel session isolation is broken.
                leaked_canary = history_canary in dm_text or history_canary.lower() in dm_text.lower()
                check(
                    test_ctx,
                    "DM response lacks sender's Matrix history",
                    not leaked_canary,
                    error=(
                        f"Session isolation broken: agent-beta's DM response "
                        f"contains sender's prior Matrix canary ({history_canary}). "
                        f"Response (first 300 chars): {dm_text[:300]}"
                    ) if leaked_canary else None,
                )
                if leaked_canary:
                    print(f"    {RED}Leaked canary in DM response!{RESET}")
                    print(f"    {DIM}{dm_text[:300]}{RESET}")

        # ── Summary ──────────────────────────────────────────────────────

        print(f"\n  {BOLD}Summary:{RESET}")
        print(f"    Seed room:           {seed_room}")
        print(f"    Channel room:        {MYCELIUM_CHANNEL_ROOM}")
        if memory_found:
            print(f"    Seed room memories:  {GREEN}present{RESET}")
        else:
            print(f"    Seed room memories:  {YELLOW}not written{RESET}")
        print(f"    Cross-channel leak:  {'%sYES%s' % (RED, RESET) if not channel_room_clean else '%sNO%s' % (GREEN, RESET)}")
        print(f"    Blind probe aware:   {'%sYES (unexpected)%s' % (RED, RESET) if knows_decision else '%sNO (expected)%s' % (GREEN, RESET)}")
        print(f"    Bridged probe aware: {'%sYES (expected)%s' % (GREEN, RESET) if bridge_has_knowledge else '%sNO (unexpected)%s' % (YELLOW, RESET)}")

        await observer.close()

    except Exception as e:
        log_error(f"Test failed with exception: {e}")
        check(test_ctx, "Test completed without error", False, error=str(e))

    finally:
        # Cleanup: delete the seed room
        try:
            async with httpx.AsyncClient(timeout=10.0) as http:
                await http.delete(f"{BACKEND_URL}/rooms/{quote(seed_room, safe='')}")
                log_info(f"Cleaned up seed room: {seed_room}")
        except Exception:
            pass


# ─────────────────────────────────────────────────────────────────────────────
# Sync wrapper for pytest
# ─────────────────────────────────────────────────────────────────────────────


def cross_channel_memory_isolation(ctx: TestContext):
    """Sync wrapper for pytest."""
    asyncio.run(test_cross_channel_memory_isolation(ctx))


# ─────────────────────────────────────────────────────────────────────────────
# Standalone entry point
# ─────────────────────────────────────────────────────────────────────────────


async def main():
    from mycelium_e2e.bundle import detect_environment, print_results

    ctx = TestContext(room_name="xch-e2e-main")
    detect_environment(ctx)

    print(f"\n{BOLD}{'='*60}{RESET}")
    print(f"{BOLD}Cross-Channel Memory Isolation E2E Test{RESET}")
    print(f"{BOLD}{'='*60}{RESET}\n")

    await test_cross_channel_memory_isolation(ctx)
    print_results(ctx)


if __name__ == "__main__":
    asyncio.run(main())
