"""Suite-wide agent + room lifecycle helpers.

Suites that opt into a shared negotiation room create all agents once in
``CommonSetup``, register them to a single parent room (one gateway-restart
burst per host, isolated from testcase execution), and reuse those agents
across every row. Per-testcase setup only spawns a fresh coordination
session inside the shared room; teardown waits for that session to finish
without unregistering agents or deleting the room. ``CommonCleanup`` drops
the room subscriptions and deletes the room.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

from libs import host_exec, sessions
from libs.host_exec import HostExecError
from libs.provisioners import AgentRef, PrereqMissing, get_provisioner
from libs.sessions import SessionError

log = logging.getLogger(__name__)


def _chown_mycelium_on_hosts(testbed: Any, hosts: set[str]) -> None:
    for host in sorted(hosts):
        device = testbed.devices.get(host)
        if device is None:
            continue
        try:
            host_exec.execute(
                device,
                'if [ -d "$HOME/.mycelium" ]; then '
                'sudo chown -R "$USER:$USER" "$HOME/.mycelium" '
                "2>/dev/null || true; fi",
                shell=True,
                timeout=20.0,
            )
        except HostExecError as exc:
            log.warning("chown failed on %s (continuing): %s", host, exc)


def setup_shared_suite_room(
    testscript: Any,
    testbed: Any,
    wants: set[tuple[str, str, str]],
    *,
    control_host: str = "hub",
    room_prefix: str = "scn-suite",
) -> str:
    """Create the suite room and register every agent once.

    Expects ``testscript.parameters['provisioned_agents']`` to already
    hold ``ensure_runtime`` refs from ``provision_*_agents``. Adds
    ``suite_shared_room`` and ``suite_control_host`` to parameters.
    """
    run_id = testscript.parameters.get("suite_run_id")
    if not run_id:
        run_id = uuid.uuid4().hex[:8]
        testscript.parameters["suite_run_id"] = run_id

    room = f"{room_prefix}-{run_id}"
    testscript.parameters["suite_shared_room"] = room
    testscript.parameters["suite_control_host"] = control_host

    control = testbed.devices.get(control_host)
    if control is None:
        raise SessionError(f"setup_shared_suite_room: control host {control_host!r} not in testbed")

    sessions.create_room(control, room)
    _chown_mycelium_on_hosts(testbed, {h for (_, _, h) in wants})

    provisioned: dict[tuple[str, str, str], AgentRef] = dict(
        testscript.parameters.get("provisioned_agents") or {}
    )
    failures: list[str] = []

    for adapter, role, host in sorted(wants):
        device = testbed.devices.get(host)
        if device is None:
            failures.append(f"{role}@{host}: no such device in testbed")
            continue
        key = (adapter, role, host)
        ref = provisioned.get(key)
        if ref is None:
            failures.append(f"{role}@{host} ({adapter}): missing ensure_runtime ref")
            continue
        try:
            provisioner = get_provisioner(adapter)
            # Use ref.handle (the actual discovered/created handle) not the
            # row role — they differ when an existing agent was reused.
            updated_ref = provisioner.register_in_room(device, ref.handle, room)
            provisioned[key] = updated_ref
        except (PrereqMissing, HostExecError) as exc:
            failures.append(f"{role}@{host} ({adapter}): register_in_room → {exc}")

    testscript.parameters["provisioned_agents"] = provisioned

    if failures:
        raise SessionError(
            "setup_shared_suite_room: failed to register "
            f"{len(failures)} agent(s):\n  " + "\n  ".join(failures)
        )

    log.info(
        "setup_shared_suite_room: room=%s agents=%d",
        room,
        len(wants),
    )
    return room


def teardown_shared_suite_room(
    testscript: Any,
    testbed: Any,
    *,
    backend_url: str | None = None,
) -> None:
    """Unregister every provisioned agent from the suite room and delete it."""
    room = testscript.parameters.get("suite_shared_room")
    if not room:
        return

    control_host = testscript.parameters.get("suite_control_host") or "hub"
    control = testbed.devices.get(control_host)
    if control is None:
        log.warning("teardown_shared_suite_room: control host %r missing", control_host)
        return

    if backend_url:
        try:
            sessions.wait_for_no_active_sessions(
                backend_url, room, timeout_seconds=sessions._SUITE_SESSION_DRAIN_SECONDS
            )
        except SessionError as exc:
            log.warning("teardown_shared_suite_room: %s", exc)

    provisioned: dict[tuple[str, str, str], AgentRef] = testscript.parameters.get("provisioned_agents") or {}
    for (adapter, role, host), ref in sorted(provisioned.items()):
        device = testbed.devices.get(host)
        if device is None:
            continue
        try:
            provisioner = get_provisioner(adapter)
            provisioner.unregister_from_room(device, ref, room)
        except Exception as exc:  # noqa: BLE001 - cleanup is best-effort
            log.warning(
                "teardown_shared_suite_room: unregister %s/%s from %s failed: %s",
                adapter,
                role,
                room,
                exc,
            )

    sessions.delete_room(control, room)
    log.info("teardown_shared_suite_room: deleted %s", room)
