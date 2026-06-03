"""Cursor adapter E2E tests — thin pytest adapter layer.

Each function records pass/fail via the TestContext check() system from bundle.py,
delegating all real work to libs/cursor.py. These are the functions imported by
tests/test_mycelium_e2e.py (test_75 through test_80).

On retirement of the pytest framework, delete this file and the corresponding
test entries in tests/test_mycelium_e2e.py.
"""

from __future__ import annotations

import time
import uuid

from mycelium_e2e.bundle import (
    TestContext,
    check,
    log_info,
    log_warning,
    log_error,
    print_section,
)
from libs.cursor import (
    HUB_HOST,
    CURSOR_SPOKE_HOSTS,
    check_cursor_agent_installed,
    check_daemon_health,
    check_ssh_connectivity,
    cleanup_cursor_workspace,
    create_cursor_agent,
    create_cursor_workspace,
    create_room,
    create_session,
    daemon_subscribe,
    daemon_unsubscribe,
    delete_room,
    invoke_agent,
    poll_session_status,
    remove_cursor_agent,
    run_mycelium_cli,
    ssh_run,
    verify_agents_md,
    wait_for_agent_response,
)


def cursor_basic_dispatch(ctx: TestContext):
    """Phase 1: Single-host basic dispatch via cc-daemon."""
    print_section(75, "Cursor basic dispatch (Phase 1)")

    handle = f"cursor-e2e-{uuid.uuid4().hex[:8]}"
    room = f"e2e-cursor-{uuid.uuid4().hex[:8]}"
    workspace = None

    try:
        daemon_ok = check_daemon_health(None)
        if not check(ctx, "Daemon healthy", daemon_ok, "mycelium-cc-daemon not responding"):
            return

        r = create_room(None, room)
        if not check(ctx, "Room created", r.ok, r.error_message):
            return

        r = daemon_subscribe(None, room)
        if not check(ctx, "Daemon subscribed", r.ok, r.error_message):
            return

        workspace = create_cursor_workspace(HUB_HOST)
        check(ctx, "Workspace created", workspace is not None, "mktemp failed on hub")
        if not workspace:
            return

        r = create_cursor_agent(None, handle, room, workspace)
        if not check(ctx, "Cursor agent created", r.ok, r.error_message):
            return

        before_ts = time.time()
        r = invoke_agent(None, handle, "Say hello to confirm you are operational.", room=room, timeout=90.0)
        check(ctx, "Agent invoked", r.ok, r.error_message)

        msg = wait_for_agent_response(room, handle, timeout_seconds=180, poll_interval=5, after_ts=before_ts)
        check(ctx, "Agent response received", msg is not None, "No response within 180s")
    finally:
        remove_cursor_agent(None, handle, room=room)
        if workspace:
            cleanup_cursor_workspace(HUB_HOST, workspace)
        daemon_unsubscribe(None, room)
        delete_room(None, room)


def cursor_workspace_drift(ctx: TestContext):
    """Phase 2: Workspace asset drift — AGENTS.md healing and rules file check."""
    print_section(76, "Cursor workspace drift (Phase 2)")

    handle = f"cursor-drift-{uuid.uuid4().hex[:8]}"
    room = f"e2e-drift-{uuid.uuid4().hex[:8]}"
    workspace = None

    try:
        daemon_ok = check_daemon_health(None)
        if not check(ctx, "Daemon healthy", daemon_ok, "mycelium-cc-daemon not responding"):
            return

        r = create_room(None, room)
        if not check(ctx, "Room created", r.ok, r.error_message):
            return

        workspace = create_cursor_workspace(HUB_HOST)
        if not check(ctx, "Workspace created", workspace is not None, "mktemp failed"):
            return

        r = create_cursor_agent(None, handle, room, workspace)
        if not check(ctx, "Agent created", r.ok, r.error_message):
            return

        has_fences = verify_agents_md(HUB_HOST, workspace)
        check(ctx, "AGENTS.md has marker fences", has_fences, "Marker fences not found in AGENTS.md")

        rules_file = f"{workspace}/.cursor/rules/mycelium.mdc"
        r = ssh_run(HUB_HOST, f"test -f {rules_file} && echo exists", timeout=10.0)
        check(ctx, "mycelium.mdc rules file exists", "exists" in r.stdout,
              "Rules file not found at .cursor/rules/mycelium.mdc")

        agents_md = f"{workspace}/AGENTS.md"
        ssh_run(HUB_HOST, f'echo "# User notes outside fences" >> {agents_md}', timeout=10.0)

        still_valid = verify_agents_md(HUB_HOST, workspace)
        check(ctx, "Marker fences intact after external edit", still_valid,
              "Fences lost after appending content")
    finally:
        remove_cursor_agent(None, handle, room=room)
        if workspace:
            cleanup_cursor_workspace(HUB_HOST, workspace)
        delete_room(None, room)


def cursor_auth_failure(ctx: TestContext):
    """Phase 3: Auth failure friendly path — no crash on missing auth."""
    print_section(77, "Cursor auth failure (Phase 3)")

    handle = f"cursor-noauth-{uuid.uuid4().hex[:8]}"
    room = f"e2e-noauth-{uuid.uuid4().hex[:8]}"
    workspace = None

    try:
        daemon_ok = check_daemon_health(None)
        if not check(ctx, "Daemon healthy", daemon_ok, "mycelium-cc-daemon not responding"):
            return

        run_mycelium_cli(None, "room", "create", room, timeout=15.0)
        workspace = create_cursor_workspace(HUB_HOST)
        if not check(ctx, "Workspace created", workspace is not None, "mktemp failed"):
            return

        r = create_cursor_agent(None, handle, room, workspace)
        if not check(ctx, "Agent created", r.ok, r.error_message):
            return

        auth_path = "~/.config/cursor/auth.json"
        ssh_run(HUB_HOST, f"cp {auth_path} {auth_path}.bak 2>/dev/null; rm -f {auth_path}", timeout=10.0)

        r = invoke_agent(None, handle, "test auth failure", room=room, timeout=60.0)
        combined = (r.stdout + r.stderr).lower()
        no_crash = r.returncode != 139 and "segfault" not in combined and "panic" not in combined
        check(ctx, "No crash on missing auth", no_crash,
              f"Daemon crashed (rc={r.returncode}): {combined[:200]}")

        has_auth_msg = "auth" in combined or "credential" in combined or "login" in combined
        check(ctx, "Actionable error message", has_auth_msg or not r.ok,
              f"Expected auth-related message, got: {combined[:200]}")
    finally:
        auth_path = "~/.config/cursor/auth.json"
        ssh_run(HUB_HOST, f"mv {auth_path}.bak {auth_path} 2>/dev/null", timeout=10.0)
        remove_cursor_agent(None, handle, room=room)
        if workspace:
            cleanup_cursor_workspace(HUB_HOST, workspace)
        run_mycelium_cli(None, "room", "delete", room, "--force", timeout=15.0)


def cursor_multi_host_dispatch(ctx: TestContext):
    """Phase 4: Multi-host dispatch — hub to spoke via ephemeral room."""
    print_section(78, "Cursor multi-host dispatch (Phase 4)")

    spoke = CURSOR_SPOKE_HOSTS.get("oclw3", "10.0.50.171")
    handle = f"cursor-spoke-{uuid.uuid4().hex[:8]}"
    room = f"e2e-multihost-{uuid.uuid4().hex[:8]}"
    workspace = None

    try:
        ssh_ok = check_ssh_connectivity(spoke)
        if not check(ctx, "SSH to spoke", ssh_ok, f"Cannot reach {spoke}", skipped=not ssh_ok,
                     skip_reason=f"SSH to {spoke} failed"):
            return

        agent_ok = check_cursor_agent_installed(spoke)
        if not check(ctx, "cursor-agent on spoke", agent_ok, skipped=not agent_ok,
                     skip_reason=f"cursor-agent not on {spoke}"):
            return

        daemon_ok = check_daemon_health(None)
        if not check(ctx, "Daemon healthy", daemon_ok, "cc-daemon not responding"):
            return

        r = create_room(None, room)
        if not check(ctx, "Room created", r.ok, r.error_message):
            return

        daemon_subscribe(None, room)
        daemon_subscribe(spoke, room)

        workspace = create_cursor_workspace(spoke)
        if not check(ctx, "Spoke workspace", workspace is not None, "mktemp on spoke failed"):
            return

        r = create_cursor_agent(spoke, handle, room, workspace)
        if not check(ctx, "Spoke agent created", r.ok, r.error_message):
            return

        before_ts = time.time()
        invoke_agent(None, handle, "Respond to confirm multi-host dispatch.", room=room, timeout=90.0)

        msg = wait_for_agent_response(room, handle, timeout_seconds=180, poll_interval=5, after_ts=before_ts)
        check(ctx, "Spoke agent responded", msg is not None, f"No response from {handle} in 180s")
    finally:
        remove_cursor_agent(spoke, handle, room=room)
        if workspace:
            cleanup_cursor_workspace(spoke, workspace)
        daemon_unsubscribe(None, room)
        daemon_unsubscribe(spoke, room)
        delete_room(None, room)


def cursor_cross_family_cursor(ctx: TestContext):
    """Phase 5a: Cross-family cursor vs cursor negotiation."""
    print_section(79, "Cursor cross-family: cursor vs cursor (Phase 5a)")

    spoke = CURSOR_SPOKE_HOSTS.get("oclw3", "10.0.50.171")
    hub_handle = f"cursor-hub-{uuid.uuid4().hex[:8]}"
    spoke_handle = f"cursor-spk-{uuid.uuid4().hex[:8]}"
    room = f"e2e-xcursor-{uuid.uuid4().hex[:8]}"
    hub_workspace = None
    spoke_workspace = None

    try:
        ssh_ok = check_ssh_connectivity(spoke)
        if not check(ctx, "SSH to spoke", ssh_ok, skipped=not ssh_ok,
                     skip_reason=f"SSH to {spoke} failed"):
            return

        agent_ok = check_cursor_agent_installed(spoke)
        if not check(ctx, "cursor-agent on spoke", agent_ok, skipped=not agent_ok,
                     skip_reason=f"cursor-agent not on {spoke}"):
            return

        r = create_room(None, room)
        if not check(ctx, "Room created", r.ok, r.error_message):
            return

        daemon_subscribe(None, room)
        daemon_subscribe(spoke, room)

        hub_workspace = create_cursor_workspace(HUB_HOST)
        check(ctx, "Hub workspace", hub_workspace is not None)
        if hub_workspace:
            r = create_cursor_agent(None, hub_handle, room, hub_workspace)
            check(ctx, "Hub cursor agent", r.ok, r.error_message)

        spoke_workspace = create_cursor_workspace(spoke)
        check(ctx, "Spoke workspace", spoke_workspace is not None)
        if spoke_workspace:
            r = create_cursor_agent(spoke, spoke_handle, room, spoke_workspace)
            check(ctx, "Spoke cursor agent", r.ok, r.error_message)

        topic = "Decide on a CI/CD pipeline tool: GitHub Actions vs GitLab CI"
        r = create_session(room, topic, [hub_handle, spoke_handle], host=None, timeout=60.0)
        if not check(ctx, "Session created", r.ok, r.error_message):
            return

        result = poll_session_status(room, timeout_seconds=600, poll_interval=10, target_status="consensus")
        check(ctx, "Consensus reached (cursor vs cursor)", result is not None,
              "No consensus within 600s")
        if result:
            log_info(f"Consensus: {str(result)[:300]}")
    finally:
        remove_cursor_agent(None, hub_handle, room=room)
        remove_cursor_agent(spoke, spoke_handle, room=room)
        if hub_workspace:
            cleanup_cursor_workspace(HUB_HOST, hub_workspace)
        if spoke_workspace:
            cleanup_cursor_workspace(spoke, spoke_workspace)
        daemon_unsubscribe(None, room)
        daemon_unsubscribe(spoke, room)
        delete_room(None, room)


def cursor_cross_family_openclaw(ctx: TestContext):
    """Phase 5b: Cross-family cursor vs openclaw negotiation."""
    print_section(80, "Cursor cross-family: cursor vs openclaw (Phase 5b)")

    cursor_handle = f"cursor-xfam-{uuid.uuid4().hex[:8]}"
    openclaw_handle = "claire-agent"
    room = f"e2e-xfamily-{uuid.uuid4().hex[:8]}"
    workspace = None

    try:
        daemon_ok = check_daemon_health(None)
        if not check(ctx, "Daemon healthy", daemon_ok, "cc-daemon not responding"):
            return

        r = create_room(None, room)
        if not check(ctx, "Room created", r.ok, r.error_message):
            return

        daemon_subscribe(None, room)

        workspace = create_cursor_workspace(HUB_HOST)
        if not check(ctx, "Workspace created", workspace is not None, "mktemp failed"):
            return

        r = create_cursor_agent(None, cursor_handle, room, workspace)
        if not check(ctx, "Cursor agent created", r.ok, r.error_message):
            return

        r = run_mycelium_cli(None, "agent", "ls", timeout=15.0)
        oc_visible = openclaw_handle in r.stdout
        if not oc_visible:
            check(ctx, "OpenClaw agent visible", False, skipped=True,
                  skip_reason=f"{openclaw_handle} not registered (mycelium#334 — adopt via 'mycelium agent add')")
            return
        check(ctx, "OpenClaw agent visible", True)

        topic = "Agree on a logging framework: structured JSON vs human-readable"
        r = create_session(room, topic, [cursor_handle, openclaw_handle], host=None, timeout=60.0)
        if not check(ctx, "Cross-family session created", r.ok, r.error_message):
            return

        result = poll_session_status(room, timeout_seconds=600, poll_interval=10, target_status="consensus")
        check(ctx, "Cross-family consensus (cursor vs openclaw)", result is not None,
              "No consensus within 600s")
        if result:
            log_info(f"Cross-family consensus: {str(result)[:300]}")
    finally:
        remove_cursor_agent(None, cursor_handle, room=room)
        if workspace:
            cleanup_cursor_workspace(HUB_HOST, workspace)
        daemon_unsubscribe(None, room)
        delete_room(None, room)
