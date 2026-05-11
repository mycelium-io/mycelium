"""
Cross-channel memory isolation and return-trip E2E test.

Proves that memory accumulated in one mycelium room is NOT automatically
visible to an agent woken in a different room's session context, tests
whether explicit context inclusion can bridge the gap, and verifies that
PR #221's cross-channel return-trip delivers consensus results back to
the originating Matrix channel.

Architecture:
  Phase 1 — Seed: Tell agent-alpha (via Matrix) to store a specific decision
            in a dedicated mycelium room.  Verify the memory was written.
  Phase 2 — Isolate: Confirm the mycelium-room channel's configured room
            has no trace of that decision.
  Phase 3 — Blind probe: Ask agent-beta (via Matrix) about the decision
            WITHOUT including context.  Expect no knowledge.
  Phase 4 — Bridged probe: Ask agent-beta the SAME question but include
            the relevant context in the message body.  Expect awareness.
  Phase 5 — Return-trip: Trigger a negotiation from Matrix, wait for
            coordination consensus, and verify the plugin auto-delivers
            a "[Mycelium return trip — …]" message back to Matrix.

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

from mycelium_e2e.distributed_e2e import wait_for_mycelium_consensus

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
    nego_room: str | None = None
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
        # Phase 5: cross-channel return-trip (PR #221)
        "Negotiation room created",
        "Negotiation trigger sent",
        "Agents joined negotiation",
        "Coordination consensus reached",
        "Return-trip delivered to Matrix",
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

        # ── Phase 5: cross-channel return-trip (PR #221) ─────────────────
        #
        # PR #221 adds auto-delivery of negotiation consensus results back
        # to the user's home channel. When coordination_consensus fires,
        # the plugin posts a "[Mycelium return trip — …]" message to
        # whichever channel session the agent first appeared in. This
        # phase verifies that mechanism end-to-end on the local Matrix
        # setup: trigger a negotiation from the agents room, wait for
        # consensus, and confirm the return-trip message lands.

        log_info("Phase 5: Cross-channel return-trip — negotiation via Matrix")

        nego_room = f"xch-nego-{uuid.uuid4().hex[:8]}"
        nego_room_created = False

        async with httpx.AsyncClient(timeout=30.0) as http:
            r = await http.post(
                f"{BACKEND_URL}/rooms",
                json={"name": nego_room, "mode": "coordination"},
            )
            nego_room_created = r.status_code in (200, 201)
            if not nego_room_created:
                log_warning(f"Negotiation room creation returned {r.status_code}: {r.text[:200]}")

        check(
            test_ctx,
            "Negotiation room created",
            nego_room_created,
            error=f"Could not create room {nego_room}" if not nego_room_created else None,
        )

        if not nego_room_created:
            for name in skip_checks[13:]:
                check(test_ctx, name, False, skipped=True,
                      skip_reason="Negotiation room creation failed")
        else:
            await asyncio.sleep(5)
            nego_trigger_ts = int(time.time() * 1000)

            nego_prompt = (
                f"@agent-alpha:local @agent-beta:local\n\n"
                f"This is a NEW independent test run. Ignore any prior sessions.\n\n"
                f"Topic: Caching strategy for {DECISION_TOKEN} — Redis vs Memcached\n"
                f"Room: {nego_room}\n\n"
                f"Positions:\n"
                f"- agent-alpha: Redis — persistence, pub/sub, richer data structures\n"
                f"- agent-beta: Memcached — simpler, faster for pure cache, less memory overhead\n\n"
                f"Run EXACTLY these commands — do NOT run any others:\n\n"
                f"1. Join the coordination session as yourself:\n"
                f"     mycelium session join --handle YOUR_HANDLE --room {nego_room} "
                f"-m \"YOUR_POSITION\"\n\n"
                f"2. Do NOT run mycelium session await. The Mycelium channel plugin "
                f"wakes you when CognitiveEngine addresses you.\n\n"
                f"3. When a tick arrives, respond via the CLI:\n"
                f"     mycelium negotiate respond accept --room {nego_room} --handle YOUR_HANDLE\n"
                f"   or, only if the tick says can_counter_offer: true:\n"
                f"     mycelium negotiate propose ISSUE=VALUE ISSUE=VALUE "
                f"--room {nego_room} --handle YOUR_HANDLE\n\n"
                f"4. After responding, return control. Continue until the negotiation concludes.\n\n"
                f"5. The result will be auto-delivered back here by the Mycelium plugin — "
                f"you do NOT need to relay it yourself.\n\n"
                f"Briefly explain your reasoning before each CLI command."
            )

            nego_html = (
                f'<a href="https://matrix.to/#/@agent-alpha:local">@agent-alpha:local</a> '
                f'<a href="https://matrix.to/#/@agent-beta:local">@agent-beta:local</a><br/><br/>'
                f"This is a NEW independent test run. Ignore any prior sessions.<br/><br/>"
                f"Topic: Caching strategy for <strong>{DECISION_TOKEN}</strong> — Redis vs Memcached<br/>"
                f"Room: <code>{nego_room}</code><br/><br/>"
                f"Positions:<br/>"
                f"- agent-alpha: Redis — persistence, pub/sub, richer data structures<br/>"
                f"- agent-beta: Memcached — simpler, faster for pure cache, less memory overhead<br/><br/>"
                f"Run EXACTLY these commands (see plain-text body for details)."
            )

            try:
                await observer.send_message(agents_room, nego_prompt, formatted_body=nego_html)
                nego_sent = True
            except Exception as exc:
                nego_sent = False
                log_error(f"Failed to send negotiation trigger: {exc}")

            check(
                test_ctx,
                "Negotiation trigger sent",
                nego_sent,
                error="Could not post negotiation prompt to agents room" if not nego_sent else None,
            )

            if not nego_sent:
                for name in skip_checks[14:]:
                    check(test_ctx, name, False, skipped=True,
                          skip_reason="Negotiation trigger send failed")
            else:
                log_info("Waiting 30s for agents to join the negotiation...")
                await asyncio.sleep(30)

                alpha_joined = await wait_for_agent_response(
                    observer, agents_room, "agent-alpha", nego_trigger_ts, timeout_seconds=60,
                )
                beta_joined = await wait_for_agent_response(
                    observer, agents_room, "agent-beta", nego_trigger_ts, timeout_seconds=60,
                )
                agents_joined = len(alpha_joined) > 0 and len(beta_joined) > 0
                check(
                    test_ctx,
                    "Agents joined negotiation",
                    agents_joined,
                    error=(
                        f"alpha responded: {len(alpha_joined) > 0}, "
                        f"beta responded: {len(beta_joined) > 0}"
                    ) if not agents_joined else None,
                )

                consensus = await wait_for_mycelium_consensus(
                    nego_room, timeout_seconds=300,
                )
                check(
                    test_ctx,
                    "Coordination consensus reached",
                    consensus is not None,
                    error=f"No consensus in {nego_room} within 300s" if consensus is None else None,
                )

                if consensus:
                    log_info("Consensus reached — polling Matrix for return-trip message...")
                    return_trip_found = False
                    deadline = time.time() + 90
                    seen_events: set[str] = set()

                    while time.time() < deadline:
                        messages = await observer.read_messages(agents_room, limit=50)
                        for msg in messages:
                            eid = msg.get("event_id", "")
                            if eid in seen_events:
                                continue
                            seen_events.add(eid)
                            if msg.get("timestamp", 0) <= nego_trigger_ts:
                                continue
                            body = msg.get("body", "")
                            if "[Mycelium return trip" in body:
                                log_info(f"Return-trip found: {body[:120]}...")
                                return_trip_found = True
                                break
                        if return_trip_found:
                            break
                        await asyncio.sleep(5)

                    check(
                        test_ctx,
                        "Return-trip delivered to Matrix",
                        return_trip_found,
                        error=(
                            "No '[Mycelium return trip' message appeared in "
                            "the agents room within 90s of consensus"
                        ) if not return_trip_found else None,
                    )
                else:
                    check(
                        test_ctx,
                        "Return-trip delivered to Matrix",
                        False,
                        skipped=True,
                        skip_reason="No consensus reached — cannot verify return-trip",
                    )

        # ── Summary ──────────────────────────────────────────────────────

        print(f"\n  {BOLD}Summary:{RESET}")
        print(f"    Seed room:           {seed_room}")
        print(f"    Negotiation room:    {nego_room}")
        print(f"    Channel room:        {MYCELIUM_CHANNEL_ROOM}")
        if memory_found:
            print(f"    Seed room memories:  {GREEN}present{RESET}")
        else:
            print(f"    Seed room memories:  {YELLOW}not written{RESET}")
        print(f"    Cross-channel leak:  {'%sYES%s' % (RED, RESET) if not channel_room_clean else '%sNO%s' % (GREEN, RESET)}")
        print(f"    Blind probe aware:   {'%sYES (unexpected)%s' % (RED, RESET) if knows_decision else '%sNO (expected)%s' % (GREEN, RESET)}")
        print(f"    Bridged probe aware: {'%sYES (expected)%s' % (GREEN, RESET) if bridge_has_knowledge else '%sNO (unexpected)%s' % (YELLOW, RESET)}")
        print(f"    Return-trip:         {'%sdelivered%s' % (GREEN, RESET) if nego_room_created and 'return_trip_found' in dir() and return_trip_found else '%snot verified%s' % (YELLOW, RESET)}")

        await observer.close()

    except Exception as e:
        log_error(f"Test failed with exception: {e}")
        check(test_ctx, "Test completed without error", False, error=str(e))

    finally:
        try:
            async with httpx.AsyncClient(timeout=10.0) as http:
                await http.delete(f"{BACKEND_URL}/rooms/{quote(seed_room, safe='')}")
                log_info(f"Cleaned up seed room: {seed_room}")
                if nego_room:
                    await http.delete(f"{BACKEND_URL}/rooms/{quote(nego_room, safe='')}")
                    log_info(f"Cleaned up negotiation room: {nego_room}")
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
