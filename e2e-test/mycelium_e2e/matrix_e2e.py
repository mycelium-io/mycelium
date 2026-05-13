"""
Matrix-based end-to-end convergence tests.

These tests verify the full integration path using Matrix as the communication
layer. They simulate what happens when agents communicate through Element/Matrix
and coordinate through the Mycelium IOC.

Architecture:
1. Create a Matrix room for the negotiation
2. Agents join Mycelium via the backend API (simulating CLI calls)
3. Monitor both Matrix and Mycelium for coordination events
4. Post updates to Matrix room to simulate agent communication
5. Verify IOC path is taken through backend/CFN logs

This validates the end-to-end integration while being automatable for CI/CD.
For full agent-driven E2E testing, use the interactive demo flow.
"""

from __future__ import annotations

import asyncio
import json
import os
import time
import uuid
from dataclasses import dataclass, field
from typing import Optional
from urllib.parse import quote

import httpx

from mycelium_e2e.bundle import (
    BACKEND_URL,
    CFN_MGMT_URL,
    TestContext,
    check,
    register_room,
    capture_backend_logs,
    capture_cfn_logs,
    check_ioc_path_in_logs,
    log_info,
    log_debug,
    log_error,
    log_warning,
    log_section,
    print_section,
    print_convergence_header,
    print_convergence_result,
    dump_negotiation_debug_info,
    GREEN, RED, YELLOW, CYAN, DIM, BOLD, RESET,
)

# Matrix configuration
MATRIX_HOMESERVER = os.environ.get("MATRIX_HOMESERVER", "http://localhost:8008")
MATRIX_SHARED_SECRET = os.environ.get(
    "MATRIX_SHARED_SECRET",
    "C&1gRZ#;M2hEp-ehNLtSPeddl^DOutp*Ls4=eDyx_+._^Y#ieY"
)


@dataclass  
class MatrixE2EContext:
    """Context for Matrix-based E2E tests."""
    test_name: str
    matrix_room_id: Optional[str] = None
    matrix_room_alias: Optional[str] = None
    mycelium_room_name: Optional[str] = None
    session_room_name: Optional[str] = None
    admin_token: Optional[str] = None
    agent_tokens: dict[str, str] = field(default_factory=dict)
    results: list = field(default_factory=list)


class MatrixClient:
    """Async Matrix client for test operations."""
    
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
    
    async def send_message(self, room_id: str, body: str, msgtype: str = "m.text") -> dict:
        txn_id = uuid.uuid4().hex
        r = await self._http.put(
            f"/_matrix/client/v3/rooms/{quote(room_id, safe='')}/send/m.room.message/{txn_id}",
            json={"msgtype": msgtype, "body": body},
        )
        r.raise_for_status()
        return r.json()
    
    async def read_messages(self, room_id: str, limit: int = 50) -> list[dict]:
        r = await self._http.get(
            f"/_matrix/client/v3/rooms/{quote(room_id, safe='')}/messages",
            params={"dir": "b", "limit": limit},
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
                    "body": ev.get("content", {}).get("body"),
                    "msgtype": ev.get("content", {}).get("msgtype"),
                })
        return messages
    
    async def join_room(self, room_id_or_alias: str) -> dict:
        r = await self._http.post(
            f"/_matrix/client/v3/join/{quote(room_id_or_alias, safe='')}",
            json={},
        )
        r.raise_for_status()
        return r.json()
    
    async def create_room(self, name: str, alias: str | None = None) -> dict:
        body = {
            "name": name,
            "preset": "public_chat",
            "visibility": "public",
        }
        if alias:
            body["room_alias_name"] = alias
        r = await self._http.post("/_matrix/client/v3/createRoom", json=body)
        r.raise_for_status()
        return r.json()


async def register_matrix_user(username: str, password: str, admin: bool = False) -> dict:
    """Register a new Matrix user using the admin API."""
    import hmac
    import hashlib
    
    async with httpx.AsyncClient(timeout=30.0) as client:
        # Try login first
        r = await client.post(
            f"{MATRIX_HOMESERVER}/_matrix/client/v3/login",
            json={"type": "m.login.password", "user": username, "password": password},
        )
        if r.status_code == 200:
            return r.json()
        
        # Get nonce for registration
        r = await client.get(f"{MATRIX_HOMESERVER}/_synapse/admin/v1/register")
        nonce = r.json()["nonce"]
        
        # Compute HMAC
        mac_content = f"{nonce}\x00{username}\x00{password}\x00{'admin' if admin else 'notadmin'}"
        mac = hmac.new(MATRIX_SHARED_SECRET.encode(), mac_content.encode(), hashlib.sha1).hexdigest()
        
        # Register
        r = await client.post(
            f"{MATRIX_HOMESERVER}/_synapse/admin/v1/register",
            json={"nonce": nonce, "username": username, "password": password, "admin": admin, "mac": mac},
        )
        r.raise_for_status()
        return r.json()


async def setup_matrix_e2e_test(ctx: MatrixE2EContext, agent_handles: list[str]) -> bool:
    """
    Set up a Matrix room and register test agents.
    
    Returns:
        True if setup succeeded
    """
    log_info(f"Setting up Matrix E2E test: {ctx.test_name}")
    
    try:
        # Get admin token
        admin_data = await register_matrix_user("e2e-admin", "admin123", admin=True)
        ctx.admin_token = admin_data["access_token"]
        log_debug("Admin token acquired")
        
        admin_client = MatrixClient(MATRIX_HOMESERVER, ctx.admin_token)
        
        # Create Matrix room
        room_alias = f"e2e-matrix-{uuid.uuid4().hex[:8]}"
        room_data = await admin_client.create_room(
            name=f"E2E Test: {ctx.test_name}",
            alias=room_alias,
        )
        ctx.matrix_room_id = room_data["room_id"]
        ctx.matrix_room_alias = f"#{room_alias}:local"
        ctx.mycelium_room_name = room_alias
        log_info(f"Created Matrix room: {ctx.matrix_room_alias}")
        
        # Register and join agents
        for handle in agent_handles:
            user_data = await register_matrix_user(handle, f"{handle}123")
            ctx.agent_tokens[handle] = user_data["access_token"]
            
            agent_client = MatrixClient(MATRIX_HOMESERVER, user_data["access_token"])
            await agent_client.join_room(ctx.matrix_room_id)
            await agent_client.close()
            log_debug(f"Agent {handle} joined Matrix room")
        
        await admin_client.close()
        return True
        
    except Exception as e:
        log_error(f"Setup failed: {e}")
        return False


async def run_matrix_e2e_negotiation(
    ctx: MatrixE2EContext,
    agents_config: list[tuple[str, str, str]],
    topic: str,
) -> tuple[bool, Optional[dict]]:
    """
    Run a negotiation with Matrix as the communication layer.
    
    Agents join via Mycelium API (simulating CLI), but status updates
    are posted to the Matrix room to demonstrate integration.
    
    Returns:
        (success, consensus_content)
    """
    log_info(f"Starting Matrix E2E negotiation: {topic}")
    
    async with httpx.AsyncClient(timeout=30.0) as http:
        # Create Mycelium room
        r = await http.post(
            f"{BACKEND_URL}/rooms",
            json={"name": ctx.mycelium_room_name, "description": f"Matrix E2E: {topic}"},
        )
        if r.status_code not in (200, 201):
            log_error(f"Failed to create Mycelium room: {r.text}")
            return False, None
        
        room_data = r.json()
        log_info(f"Created Mycelium room with IOC: mas_id={room_data.get('mas_id')}")
        
        if not room_data.get("mas_id") or not room_data.get("workspace_id"):
            log_error("IOC not configured for room")
            return False, None
        
        # Post start message to Matrix
        admin_client = MatrixClient(MATRIX_HOMESERVER, ctx.admin_token)
        await admin_client.send_message(
            ctx.matrix_room_id,
            f"🤖 **Negotiation Started**\n\nTopic: {topic}\n\nAgents are joining...",
        )
        
        # Have agents join via Mycelium API
        session_room = None
        for handle, display_name, position in agents_config:
            # Post to Matrix
            if handle in ctx.agent_tokens:
                agent_client = MatrixClient(MATRIX_HOMESERVER, ctx.agent_tokens[handle])
                await agent_client.send_message(
                    ctx.matrix_room_id,
                    f"📝 **{display_name}** joining with position:\n> {position}",
                )
                await agent_client.close()
            
            # Join via Mycelium API
            r = await http.post(
                f"{BACKEND_URL}/rooms/{quote(ctx.mycelium_room_name, safe='')}/sessions",
                json={"agent_handle": handle, "intent": position},
            )
            if r.status_code in (200, 201):
                log_debug(f"{handle} joined session (status={r.status_code})")
            else:
                log_error(f"{handle} failed to join: {r.status_code} {r.text}")
            
            await asyncio.sleep(0.5)
        
        # Resolve session room via coordination sessions endpoint
        coord_r = await http.get(
            f"{BACKEND_URL}/rooms/{quote(ctx.mycelium_room_name, safe='')}/sessions/coordination",
        )
        if coord_r.status_code == 200:
            coord_sessions = coord_r.json()
            for cs in coord_sessions:
                dn = cs.get("display_name")
                if dn:
                    session_room = dn
                    ctx.session_room_name = session_room
                    break
        log_debug(f"Resolved session room: {session_room}")
        
        if not session_room:
            log_error("No session room created")
            await admin_client.close()
            return False, None
        
        log_info(f"Session room: {session_room}")
        
        # Wait for tick
        log_info("Waiting for coordination_tick...")
        tick_seen = False
        for _ in range(60):
            r = await http.get(
                f"{BACKEND_URL}/rooms/{quote(session_room, safe='')}/messages",
                params={"limit": 30}
            )
            if r.status_code == 200:
                for msg in r.json().get("messages", []):
                    if msg.get("message_type") == "coordination_tick":
                        tick_seen = True
                        log_info("coordination_tick received")
                        break
            if tick_seen:
                break
            await asyncio.sleep(5)
        
        if not tick_seen:
            log_error("No tick received")
            await admin_client.close()
            return False, None
        
        # Post tick notification to Matrix
        await admin_client.send_message(
            ctx.matrix_room_id,
            "⏳ **Coordination tick received** - Agents are deliberating...",
        )
        
        # Respond accept for all agents
        for handle, _, _ in agents_config:
            r = await http.post(
                f"{BACKEND_URL}/rooms/{quote(session_room, safe='')}/messages",
                json={
                    "sender_handle": handle,
                    "message_type": "broadcast",
                    "content": json.dumps({"action": "accept"}),
                },
            )
            log_debug(f"{handle} responded accept")
            await asyncio.sleep(1)
        
        # Wait for consensus
        log_info("Waiting for coordination_consensus...")
        consensus_content = None
        for _ in range(60):
            r = await http.get(
                f"{BACKEND_URL}/rooms/{quote(session_room, safe='')}/messages",
                params={"limit": 30}
            )
            if r.status_code == 200:
                for msg in r.json().get("messages", []):
                    if msg.get("message_type") == "coordination_consensus":
                        try:
                            consensus_content = json.loads(msg.get("content", "{}"))
                        except json.JSONDecodeError:
                            consensus_content = {"raw": msg.get("content")}
                        log_info("coordination_consensus received")
                        break
            if consensus_content:
                break
            await asyncio.sleep(5)
        
        # Post result to Matrix
        if consensus_content:
            plan = consensus_content.get("plan", "")[:200]
            await admin_client.send_message(
                ctx.matrix_room_id,
                f"✅ **Consensus Reached!**\n\n{plan}...",
                msgtype="m.notice",
            )
        else:
            await admin_client.send_message(
                ctx.matrix_room_id,
                "❌ **No consensus reached** - Agents did not converge.",
                msgtype="m.notice",
            )
        
        await admin_client.close()
        return consensus_content is not None, consensus_content


async def cleanup_matrix_e2e_test(ctx: MatrixE2EContext):
    """Clean up after test."""
    log_info(f"Cleaning up: {ctx.test_name}")
    if ctx.mycelium_room_name:
        async with httpx.AsyncClient(timeout=30.0) as http:
            await http.delete(f"{BACKEND_URL}/rooms/{quote(ctx.mycelium_room_name, safe='')}")


# ─────────────────────────────────────────────────────────────────────────────
# Test: Two-Agent Negotiation via Matrix
# ─────────────────────────────────────────────────────────────────────────────

async def test_matrix_two_agent_negotiation(test_ctx: TestContext):
    """Two agents negotiate through Matrix with IOC coordination."""
    print_section(30, "Matrix E2E: Two-agent negotiation")
    
    agents_config = [
        ("matrix-features", "Features Team",
         "Prioritize new features. We need 70% capacity for roadmap items."),
        ("matrix-stability", "Stability Team",
         "Focus on stability. Need 60% capacity for bug fixes and tech debt."),
    ]
    
    print_convergence_header("Sprint Planning (Matrix + IOC)", agents_config)
    
    ctx = MatrixE2EContext(test_name="two-agent-sprint")
    
    skip_checks = [
        "Matrix room created",
        "Agents joined Matrix room",
        "Mycelium room has IOC path",
        "coordination_consensus received",
        "Consensus is substantive",
        "IOC path verified in logs",
        "Matrix messages posted",
    ]
    
    if test_ctx.skip_llm_tests:
        for name in skip_checks:
            check(test_ctx, name, False, skipped=True, skip_reason="LLM unavailable")
        return
    
    try:
        agent_handles = [h for h, _, _ in agents_config]
        setup_ok = await setup_matrix_e2e_test(ctx, agent_handles)
        if ctx.mycelium_room_name:
            register_room(test_ctx, ctx.mycelium_room_name)
        check(test_ctx, "Matrix room created", setup_ok and ctx.matrix_room_id is not None)
        check(test_ctx, "Agents joined Matrix room", len(ctx.agent_tokens) == 2)
        
        if not setup_ok:
            for name in skip_checks[2:]:
                check(test_ctx, name, False, skipped=True, skip_reason="Setup failed")
            return
        
        success, consensus = await run_matrix_e2e_negotiation(
            ctx, agents_config, "Sprint Capacity Allocation"
        )
        
        # Check IOC path
        async with httpx.AsyncClient(timeout=30.0) as http:
            r = await http.get(f"{BACKEND_URL}/rooms/{quote(ctx.mycelium_room_name, safe='')}")
            room_info = r.json() if r.status_code == 200 else {}
        
        ioc_configured = bool(room_info.get("mas_id") and room_info.get("workspace_id"))
        check(test_ctx, "Mycelium room has IOC path", ioc_configured)
        
        check(test_ctx, "coordination_consensus received", success and consensus is not None,
              error="No consensus" if not success else None)
        
        substantive = False
        if consensus:
            plan = str(consensus.get("plan", ""))
            assignments = consensus.get("assignments", {})
            broken = consensus.get("broken", False)
            if not broken and (len(assignments) >= 1 or len(plan) > 30):
                substantive = True
        check(test_ctx, "Consensus is substantive", substantive)
        
        # Verify IOC path in logs
        backend_logs = capture_backend_logs(200)
        cfn_logs = capture_cfn_logs(100)
        ioc_indicators = check_ioc_path_in_logs(backend_logs, cfn_logs)
        ioc_verified = ioc_indicators.get("cfn_mas_created") or ioc_indicators.get("cfn_llm_called")
        check(test_ctx, "IOC path verified in logs", ioc_verified)
        
        # Verify Matrix messages were posted
        admin_client = MatrixClient(MATRIX_HOMESERVER, ctx.admin_token)
        messages = await admin_client.read_messages(ctx.matrix_room_id, limit=20)
        await admin_client.close()
        matrix_msgs_ok = len(messages) >= 3
        check(test_ctx, "Matrix messages posted", matrix_msgs_ok)
        
        print_convergence_result(consensus, substantive)
        
    finally:
        await cleanup_matrix_e2e_test(ctx)
        print(f"    {DIM}Matrix room: {ctx.matrix_room_alias}{RESET}")
        print(f"    {DIM}Mycelium room: {ctx.mycelium_room_name}{RESET}")


# ─────────────────────────────────────────────────────────────────────────────
# Test: Three-Agent Negotiation via Matrix
# ─────────────────────────────────────────────────────────────────────────────

async def test_matrix_three_agent_negotiation(test_ctx: TestContext):
    """Three agents negotiate release planning through Matrix."""
    print_section(31, "Matrix E2E: Three-agent negotiation")
    
    agents_config = [
        ("matrix-speed", "Speed Advocate",
         "Release ASAP with minimal testing. Speed to market is critical."),
        ("matrix-quality", "Quality Advocate",
         "Comprehensive testing required. Quality issues damage reputation."),
        ("matrix-cost", "Cost Advocate",
         "Minimize resources. Staged rollout balances speed and quality."),
    ]
    
    print_convergence_header("Release Planning (Matrix + IOC)", agents_config)
    
    ctx = MatrixE2EContext(test_name="three-agent-release")
    
    skip_checks = [
        "Matrix room created",
        "All agents joined",
        "IOC path configured",
        "coordination_consensus received",
        "Consensus is substantive",
        "IOC path verified in logs",
    ]
    
    if test_ctx.skip_llm_tests:
        for name in skip_checks:
            check(test_ctx, name, False, skipped=True, skip_reason="LLM unavailable")
        return
    
    try:
        agent_handles = [h for h, _, _ in agents_config]
        setup_ok = await setup_matrix_e2e_test(ctx, agent_handles)
        if ctx.mycelium_room_name:
            register_room(test_ctx, ctx.mycelium_room_name)
        check(test_ctx, "Matrix room created", setup_ok)
        check(test_ctx, "All agents joined", len(ctx.agent_tokens) == 3)
        
        if not setup_ok:
            for name in skip_checks[2:]:
                check(test_ctx, name, False, skipped=True, skip_reason="Setup failed")
            return
        
        success, consensus = await run_matrix_e2e_negotiation(
            ctx, agents_config, "Software Release Planning"
        )
        
        async with httpx.AsyncClient(timeout=30.0) as http:
            r = await http.get(f"{BACKEND_URL}/rooms/{quote(ctx.mycelium_room_name, safe='')}")
            room_info = r.json() if r.status_code == 200 else {}
        
        check(test_ctx, "IOC path configured", bool(room_info.get("mas_id")))
        check(test_ctx, "coordination_consensus received", success and consensus is not None)
        
        substantive = False
        if consensus:
            plan = str(consensus.get("plan", ""))
            assignments = consensus.get("assignments", {})
            if not consensus.get("broken") and (len(assignments) >= 2 or len(plan) > 50):
                substantive = True
        check(test_ctx, "Consensus is substantive", substantive)
        
        backend_logs = capture_backend_logs(200)
        cfn_logs = capture_cfn_logs(100)
        ioc_indicators = check_ioc_path_in_logs(backend_logs, cfn_logs)
        check(test_ctx, "IOC path verified in logs", 
              ioc_indicators.get("cfn_mas_created") or ioc_indicators.get("cfn_llm_called"))
        
        print_convergence_result(consensus, substantive)
        
    finally:
        await cleanup_matrix_e2e_test(ctx)
        print(f"    {DIM}Mycelium room: {ctx.mycelium_room_name}{RESET}")


# ─────────────────────────────────────────────────────────────────────────────
# Test: Architecture Decision via Matrix
# ─────────────────────────────────────────────────────────────────────────────

async def test_matrix_architecture_decision(test_ctx: TestContext):
    """Two agents negotiate a technical architecture decision."""
    print_section(32, "Matrix E2E: Architecture decision")
    
    agents_config = [
        ("matrix-postgres", "PostgreSQL Advocate",
         "PostgreSQL: ACID compliance, mature ecosystem, pgvector for AI."),
        ("matrix-mongo", "MongoDB Advocate",
         "MongoDB: schema flexibility, horizontal scaling, faster iteration."),
    ]
    
    print_convergence_header("Database Selection (Matrix + IOC)", agents_config)
    
    ctx = MatrixE2EContext(test_name="arch-decision")
    
    skip_checks = [
        "Matrix room created",
        "Agents joined",
        "IOC path configured",
        "coordination_consensus received",
        "Consensus has technical rationale",
        "IOC path verified in logs",
    ]
    
    if test_ctx.skip_llm_tests:
        for name in skip_checks:
            check(test_ctx, name, False, skipped=True, skip_reason="LLM unavailable")
        return
    
    try:
        agent_handles = [h for h, _, _ in agents_config]
        setup_ok = await setup_matrix_e2e_test(ctx, agent_handles)
        if ctx.mycelium_room_name:
            register_room(test_ctx, ctx.mycelium_room_name)
        check(test_ctx, "Matrix room created", setup_ok)
        check(test_ctx, "Agents joined", len(ctx.agent_tokens) == 2)
        
        if not setup_ok:
            for name in skip_checks[2:]:
                check(test_ctx, name, False, skipped=True, skip_reason="Setup failed")
            return
        
        success, consensus = await run_matrix_e2e_negotiation(
            ctx, agents_config, "Database Technology Selection"
        )
        
        async with httpx.AsyncClient(timeout=30.0) as http:
            r = await http.get(f"{BACKEND_URL}/rooms/{quote(ctx.mycelium_room_name, safe='')}")
            room_info = r.json() if r.status_code == 200 else {}
        
        check(test_ctx, "IOC path configured", bool(room_info.get("mas_id")))
        check(test_ctx, "coordination_consensus received", success and consensus is not None)
        
        has_rationale = False
        if consensus:
            plan = str(consensus.get("plan", "")).lower()
            assignments = consensus.get("assignments", {})
            tech_terms = ["postgres", "mongo", "database", "sql", "schema", "acid", "scaling"]
            if any(term in plan for term in tech_terms) or len(assignments) > 0:
                has_rationale = True
        check(test_ctx, "Consensus has technical rationale", has_rationale)
        
        backend_logs = capture_backend_logs(200)
        cfn_logs = capture_cfn_logs(100)
        ioc_indicators = check_ioc_path_in_logs(backend_logs, cfn_logs)
        check(test_ctx, "IOC path verified in logs",
              ioc_indicators.get("cfn_mas_created") or ioc_indicators.get("cfn_llm_called"))
        
        print_convergence_result(consensus, has_rationale)
        
    finally:
        await cleanup_matrix_e2e_test(ctx)
        print(f"    {DIM}Mycelium room: {ctx.mycelium_room_name}{RESET}")


# ─────────────────────────────────────────────────────────────────────────────
# Synchronous wrappers for pytest
# ─────────────────────────────────────────────────────────────────────────────

def matrix_two_agent_negotiation(ctx: TestContext):
    """Sync wrapper for pytest."""
    asyncio.run(test_matrix_two_agent_negotiation(ctx))


def matrix_three_agent_negotiation(ctx: TestContext):
    """Sync wrapper for pytest."""
    asyncio.run(test_matrix_three_agent_negotiation(ctx))


def matrix_architecture_decision(ctx: TestContext):
    """Sync wrapper for pytest."""
    asyncio.run(test_matrix_architecture_decision(ctx))


# ─────────────────────────────────────────────────────────────────────────────
# Main entry point for standalone testing
# ─────────────────────────────────────────────────────────────────────────────

async def main():
    """Run all Matrix E2E tests."""
    from mycelium_e2e.bundle import detect_environment, print_results
    
    ctx = TestContext(room_name="matrix-e2e-main")
    detect_environment(ctx)
    
    print(f"\n{BOLD}{'='*60}{RESET}")
    print(f"{BOLD}Matrix End-to-End Convergence Tests{RESET}")
    print(f"{BOLD}{'='*60}{RESET}")
    print(f"\nThese tests use Matrix as the communication layer.")
    print(f"Agents coordinate through Matrix + Mycelium IOC.\n")
    
    await test_matrix_two_agent_negotiation(ctx)
    await test_matrix_three_agent_negotiation(ctx)
    await test_matrix_architecture_decision(ctx)
    
    print_results(ctx)


if __name__ == "__main__":
    asyncio.run(main())
