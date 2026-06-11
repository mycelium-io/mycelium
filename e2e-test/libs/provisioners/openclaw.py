"""OpenClaw provisioner: wraps :mod:`libs.openclaw` via :mod:`libs.host_exec`.

OpenClaw agents are typically pre-configured on each host (see the
existing ``DISTRIBUTED_AGENTS`` dict in
:mod:`testcases.distributed_tests`). Stage 1 of the three-axis matrix
refactor preserves that assumption: :meth:`OpenClawProvisioner.create_agent`
verifies the agent is reachable via ``mycelium agent ls`` rather than
auto-creating one. Auto-creation lands in stage 2 alongside the
unified spoke image.

The wake path posts a Matrix DM (via :class:`libs.matrix_client.MatrixClient`)
when the device is a *spoke* and Matrix credentials are configured;
hub-resident agents see the session via the openclaw mycelium-room
channel plugin and need no external trigger.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from typing import Any, ClassVar

from libs import host_exec
from libs.host_exec import HostExecError
from libs.provisioners.base import (
    BOOTSTRAP_ROOM,
    ABCProvisioner,
    AgentRef,
    PrereqMissing,
)

log = logging.getLogger(__name__)


# When OpenClaw agents are spawned by the test harness they need
# credentials. ``mycelium agent create --copy-auth-from <seed>``
# duplicates an existing agent's ``auth-profiles.json`` so the new
# agent can authenticate. The seed handle is read from this env var
# (set during lab provisioning / CI bootstrap).
SEED_AGENT_ENV = "MYCELIUM_E2E_OPENCLAW_SEED_AGENT"


class OpenClawProvisioner(ABCProvisioner):
    """Provisioner for the openclaw adapter.

    Read carefully: the constructor takes no arguments. The provisioner
    is intentionally stateless; per-device configuration travels through
    the pyATS Device's ``custom`` block (and is read on each call via
    :mod:`libs.host_exec`).
    """

    name: ClassVar[str] = "openclaw"

    # ── prereqs ────────────────────────────────────────────────────────

    def check_prereqs(self, device: Any) -> None:
        """Verify the mycelium CLI is reachable on ``device``.

        Raises :class:`PrereqMissing` so scenarios can convert to a
        ``self.skipped(...)`` cleanly.
        """
        try:
            result = host_exec.execute(
                device,
                ["mycelium", "--version"],
                timeout=15.0,
            )
        except HostExecError as exc:
            raise PrereqMissing(f"openclaw: dispatch failed: {exc}") from exc
        if result.returncode != 0:
            raise PrereqMissing(
                f"openclaw: `mycelium --version` exited {result.returncode}: {result.stderr.strip()[:200]}"
            )

    # ── create ────────────────────────────────────────────────────────

    # ── new two-phase lifecycle ───────────────────────────────────────

    def ensure_runtime(
        self,
        device: Any,
        handle: str,
        *,
        bootstrap_room: str = BOOTSTRAP_ROOM,
        seed_agent: str | None = None,
        **kwargs: Any,  # noqa: ARG002 - reserved for adapter-specific options
    ) -> AgentRef:
        """Ensure the OpenClaw runtime + bootstrap manifest exist.

        Idempotent. On the lab this:
        1. Verifies ``bootstrap_room`` exists (creates it if not).
        2. Runs ``mycelium agent ls --room <bootstrap_room>``; if
           ``handle`` is already listed, returns its ref.
        3. Otherwise ``mycelium agent create <handle> --adapter
           openclaw --room <bootstrap_room> [--copy-auth-from <seed>]``.

        Seed agent resolution (first match wins):

        1. ``seed_agent`` kwarg (explicit override from caller).
        2. ``device.custom["openclaw_seed_agent"]`` (per-host config
           in the testbed YAML — different hosts often have
           different pre-authed seed agents).
        3. ``MYCELIUM_E2E_OPENCLAW_SEED_AGENT`` env var (shared
           value across the run).
        4. None — new agent created without auth. Fine for
           offline / dispatch-only tests; broken for anything
           that calls an LLM.
        """
        device_label = host_exec.describe(device)
        log.info("openclaw.ensure_runtime: %s on %s", handle, device_label)

        # 1) Bootstrap room — create it (idempotent: returns 0 even
        # if already exists, in the current CLI).
        self._ensure_room(device, bootstrap_room)

        # 2) Already-present fast path. ``mycelium agent ls`` returns
        # an empty body (and rc=0) if the room is empty, so the
        # "handle in stdout" check is the source of truth.
        existing = self._list_agents_in_room(device, bootstrap_room)
        if handle in existing:
            log.info(
                "openclaw.ensure_runtime: %s already present in %s on %s",
                handle,
                bootstrap_room,
                device_label,
            )
            return AgentRef(
                handle=handle,
                adapter=self.name,
                device_name=getattr(device, "name", None) or device_label,
                metadata={
                    "matrix_token_env": _matrix_token_env_for(handle),
                    "bootstrap_room": bootstrap_room,
                    "pre_existing": True,
                },
            )

        # 3) Fresh create. ``mycelium agent create`` for openclaw
        # spawns an OpenClaw runtime + writes a manifest in the
        # provided room. ``--copy-auth-from`` is the only way to make
        # the new agent able to authenticate against the LLM.
        seed = seed_agent or _seed_agent_for(device)
        argv = [
            "mycelium",
            "agent",
            "create",
            handle,
            "--adapter",
            "openclaw",
            "--room",
            bootstrap_room,
            "--as",
            "e2e-runner",
        ]
        if seed:
            argv.extend(["--copy-auth-from", seed])
        try:
            result = host_exec.execute(device, argv, timeout=120.0)
        except HostExecError as exc:
            raise PrereqMissing(f"openclaw: agent create dispatch failed for {handle}: {exc}") from exc

        # ``mycelium agent create`` races with the backend over file
        # ownership: the backend writes ``agents/<handle>.md`` as
        # root (Docker volume mount), then the CLI tries to update
        # it as the user. On a fresh host the CLI loses that race
        # and exits 1 even though the OpenClaw runtime got spawned.
        # Reclaim ownership and retry once — usually enough to
        # convert the failure into a clean success.
        if result.returncode != 0 and "is owned by root" in (result.stderr or ""):
            log.info(
                "openclaw.ensure_runtime: %s hit root-ownership race; "
                "chowning and retrying",
                handle,
            )
            host_exec.execute(
                device,
                'if [ -d "$HOME/.mycelium" ]; then '
                'sudo chown -R "$USER:$USER" "$HOME/.mycelium" '
                "2>/dev/null || true; fi",
                shell=True,
                timeout=20.0,
            )
            try:
                result = host_exec.execute(device, argv, timeout=120.0)
            except HostExecError as exc:
                raise PrereqMissing(
                    f"openclaw: agent create retry dispatch failed for {handle}: {exc}"
                ) from exc

        if result.returncode != 0:
            # ``mycelium agent create`` is the heaviest call we make
            # in setup — surface BOTH streams so debugging doesn't
            # require digging through pyats archive logs.
            raise PrereqMissing(
                f"openclaw: agent create failed for {handle!r} "
                f"(exit {result.returncode}): "
                f"stdout={result.stdout.strip()[:300]} "
                f"stderr={result.stderr.strip()[:300]}"
            )

        # Final chown — keeps ``register_in_room`` from tripping
        # over fresh root-owned files written by the backend during
        # the create.
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
            log.debug("openclaw.ensure_runtime: post-create chown failed: %s", exc)

        return AgentRef(
            handle=handle,
            adapter=self.name,
            device_name=getattr(device, "name", None) or device_label,
            metadata={
                "matrix_token_env": _matrix_token_env_for(handle),
                "bootstrap_room": bootstrap_room,
                "pre_existing": False,
            },
        )

    def register_in_room(
        self,
        device: Any,
        handle: str,
        room: str,
        *,
        opening: str | None = None,  # noqa: ARG002 - opening lives on the session join, not the manifest
    ) -> AgentRef:
        """Adopt the already-provisioned agent into ``room``.

        Lightweight: writes a per-room manifest only — does NOT spawn
        any new runtime. ``mycelium agent add <handle> --room <room>``
        is idempotent on the CLI side, so re-running is harmless.

        Same root-ownership race as :meth:`ensure_runtime`: the
        backend (Docker, runs as root) writes the per-room manifest
        first, then the CLI tries to update it. Reclaim ownership
        and retry once on the canonical error string.
        """
        argv = [
            "mycelium",
            "agent",
            "add",
            handle,
            "--room",
            room,
            "--as",
            "e2e-runner",
            "--description",
            f"matrix-scenario {handle} in {room}",
        ]
        try:
            result = host_exec.execute(device, argv, timeout=30.0)
        except HostExecError as exc:
            raise PrereqMissing(f"openclaw: agent add dispatch failed for {handle}: {exc}") from exc

        if result.returncode != 0 and "is owned by root" in (result.stderr or ""):
            log.info(
                "openclaw.register_in_room: %s in %s hit root-ownership race; "
                "chowning and retrying",
                handle,
                room,
            )
            host_exec.execute(
                device,
                'if [ -d "$HOME/.mycelium" ]; then '
                'sudo chown -R "$USER:$USER" "$HOME/.mycelium" '
                "2>/dev/null || true; fi",
                shell=True,
                timeout=20.0,
            )
            try:
                result = host_exec.execute(device, argv, timeout=30.0)
            except HostExecError as exc:
                raise PrereqMissing(
                    f"openclaw: agent add retry dispatch failed for {handle}: {exc}"
                ) from exc

        if result.returncode != 0:
            raise PrereqMissing(
                f"openclaw: `mycelium agent add {handle} --room {room}` "
                f"exited {result.returncode}: "
                f"{result.stderr.strip() or result.stdout.strip()}"
            )

        return AgentRef(
            handle=handle,
            adapter=self.name,
            device_name=getattr(device, "name", None) or str(device),
            metadata={
                "matrix_token_env": _matrix_token_env_for(handle),
                "room": room,
            },
        )

    def unregister_from_room(self, device: Any, agent: AgentRef, room: str) -> None:
        """Drop the per-room manifest AND reset session state.

        Two passes:

        1. ``mycelium agent rm <handle> --room <room> --force`` —
           drops the manifest from this scenario's room.
        2. ``openclaw gateway call sessions.reset`` for every
           mycelium-room session attached to this agent — clears
           the underlying Claude Code context so the next scenario
           starts fresh.

        Best-effort: failures in either pass are logged, not raised.
        The scenario's own cleanup deletes the room regardless.
        """
        # 1) drop the room manifest (lightweight; openclaw runtime
        # survives for the next scenario)
        try:
            result = host_exec.execute(
                device,
                [
                    "mycelium",
                    "agent",
                    "rm",
                    agent.handle,
                    "--room",
                    room,
                    "--force",
                ],
                timeout=30.0,
            )
        except HostExecError as exc:
            log.warning(
                "openclaw.unregister_from_room: dispatch failed for %s in %s: %s",
                agent.handle,
                room,
                exc,
            )
        else:
            if result.returncode != 0:
                log.warning(
                    "openclaw.unregister_from_room: %s in %s exited %d: %s",
                    agent.handle,
                    room,
                    result.returncode,
                    result.stderr.strip()[:200],
                )

        # 2) reset gateway-side session state (legacy cleanup_agent
        # behaviour — preserved here so scenarios don't accumulate
        # ghost sessions across runs)
        self.cleanup_agent(device, agent, room)

    def teardown_runtime(self, device: Any, agent: AgentRef) -> None:
        """Destroy the OpenClaw runtime + bootstrap manifest.

        Skip when the agent was pre-existing (we didn't create it,
        we don't own its lifecycle — keep the operator's pre-baked
        agents around for the next run).
        """
        if agent.metadata.get("pre_existing"):
            log.info(
                "openclaw.teardown_runtime: %s was pre-existing; leaving alone",
                agent.handle,
            )
            return

        bootstrap_room = agent.metadata.get("bootstrap_room") or BOOTSTRAP_ROOM
        try:
            result = host_exec.execute(
                device,
                [
                    "mycelium",
                    "agent",
                    "rm",
                    agent.handle,
                    "--room",
                    bootstrap_room,
                    "--full",
                    "--force",
                ],
                timeout=60.0,
            )
        except HostExecError as exc:
            log.warning(
                "openclaw.teardown_runtime: dispatch failed for %s: %s",
                agent.handle,
                exc,
            )
            return
        if result.returncode != 0:
            log.warning(
                "openclaw.teardown_runtime: %s exited %d: %s",
                agent.handle,
                result.returncode,
                result.stderr.strip()[:200],
            )

    # ── legacy create_agent shim ──────────────────────────────────────

    def create_agent(
        self,
        device: Any,
        handle: str,
        room: str,
        *,
        opening: str | None = None,
    ) -> AgentRef:
        """Legacy one-shot: ``ensure_runtime`` + ``register_in_room``.

        Kept so anyone still calling the old API works; new tests use
        the two-phase form directly so the heavy ``ensure_runtime``
        runs once in common_setup instead of every testcase.
        """
        self.ensure_runtime(device, handle)
        return self.register_in_room(device, handle, room, opening=opening)

    # ── helpers ───────────────────────────────────────────────────────

    def _ensure_room(self, device: Any, room: str) -> None:
        """Create ``room`` and reclaim file ownership.

        Two-step:

        1. ``mycelium room create <room>`` — idempotent (non-zero
           exit on "already exists" is silently OK).
        2. ``sudo chown -R $USER:$USER ~/.mycelium/rooms/<room>``
           if the directory exists.

        Step 2 is the subtle one. The backend runs as root inside
        its Docker container and creates ``~/.mycelium/rooms/<room>/``
        through a volume mount, so subsequent ``mycelium agent
        create`` calls — which write the local manifest as the SSH
        user — fail with "Cannot write … owned by root". Reclaiming
        ownership before handing off to ``agent create`` is the
        simplest fix that doesn't require changing the backend.
        ``$USER`` on lab boxes is ``ubuntu`` with passwordless sudo
        (same convention as ``libs.lab_redeploy._DATA_DIRS_WIPE``).
        """
        try:
            result = host_exec.execute(
                device,
                ["mycelium", "room", "create", room],
                timeout=15.0,
            )
        except HostExecError as exc:
            log.debug("openclaw._ensure_room: dispatch failed (ignoring): %s", exc)
            return
        if result.returncode != 0 and "already exists" not in (
            result.stderr.lower() + result.stdout.lower()
        ):
            log.debug(
                "openclaw._ensure_room: %s exit=%d stderr=%s",
                room,
                result.returncode,
                result.stderr.strip()[:120],
            )

        # Reclaim ownership of the room dir. ``shell=True`` here so
        # ``$USER`` and ``$HOME`` are expanded by the remote shell,
        # not on the runner side. Best-effort: a chown failure
        # (e.g. running locally without sudo) downgrades to a debug
        # log — agent create will then surface the real error.
        try:
            host_exec.execute(
                device,
                (
                    f'if [ -d "$HOME/.mycelium/rooms/{room}" ]; then '
                    f'sudo chown -R "$USER:$USER" "$HOME/.mycelium/rooms/{room}" '
                    f"2>/dev/null || true; fi"
                ),
                shell=True,
                timeout=15.0,
            )
        except HostExecError as exc:
            log.debug("openclaw._ensure_room: chown skipped: %s", exc)

    def _list_agents_in_room(self, device: Any, room: str) -> set[str]:
        """Return the set of agent handles registered in ``room``.

        Empty set on any failure — callers treat "not present" as "needs
        creating" which is the safe direction.
        """
        try:
            result = host_exec.execute(
                device,
                ["mycelium", "agent", "ls", "--room", room],
                timeout=15.0,
            )
        except HostExecError:
            return set()
        if result.returncode != 0:
            return set()
        # ``mycelium agent ls`` output: one line per agent, handle in
        # the first whitespace-separated column. Skip blank lines and
        # the "No agents" advisory line if present.
        handles: set[str] = set()
        for line in result.stdout.splitlines():
            line = line.strip()
            if not line or line.lower().startswith("no agents"):
                continue
            # Header rows from Rich tables start with a separator;
            # the first column is the handle for both Rich and plain
            # output.
            first = line.split()[0]
            # Strip leading '@' in case the CLI ever prefixes handles
            # for display.
            handles.add(first.lstrip("@"))
        return handles

    # ── wake ──────────────────────────────────────────────────────────

    def wake_agent(
        self,
        device: Any,
        agent: AgentRef,
        session_room: str,
    ) -> None:
        """Post a Matrix DM trigger when ``device`` is a spoke.

        On the hub the openclaw mycelium-room channel plugin sees the
        session sub-room directly and no Matrix prod is needed. On
        spokes we fall back to the existing Matrix-trigger path that
        :mod:`testcases.distributed_tests` uses.
        """
        custom = getattr(device, "custom", {})
        role = (custom.get("role") if hasattr(custom, "get") else None) or ""
        if role.lower() != "spoke":
            log.debug(
                "openclaw.wake_agent: %s is %r, no Matrix trigger needed",
                host_exec.describe(device),
                role or "hub",
            )
            return

        matrix_url = os.environ.get("MATRIX_URL")
        room_id = os.environ.get("E2E_MATRIX_ROOM_ID")
        token = os.environ.get(agent.metadata.get("matrix_token_env", ""))
        if not (matrix_url and room_id and token):
            log.info(
                "openclaw.wake_agent: skipping Matrix trigger (matrix_url=%s, room_id=%s, token=%s)",
                bool(matrix_url),
                bool(room_id),
                bool(token),
            )
            return

        body = (
            f"@{agent.handle} please join the negotiation in room "
            f"{session_room}. Use `mycelium session join --room {session_room}`."
        )
        try:
            asyncio.run(_send_matrix_dm(matrix_url, token, room_id, body))
        except Exception as exc:  # noqa: BLE001 - logged and continued
            log.warning(
                "openclaw.wake_agent: Matrix trigger to %s failed: %s",
                agent.handle,
                exc,
            )

    # ── cleanup ───────────────────────────────────────────────────────

    def cleanup_agent(
        self,
        device: Any,
        agent: AgentRef,
        room: str,  # noqa: ARG002 - room is part of the matrix row, scenarios delete it
    ) -> None:
        """Best-effort reset of the agent's negotiation-carrying sessions.

        Mirrors :func:`libs.openclaw.reset_agent_sessions` but speaks
        through :mod:`host_exec`. Failures are logged, not raised - the
        scenario's own cleanup step deletes the test room regardless.
        """
        try:
            sessions = self._list_negotiation_sessions(device, agent.handle)
        except HostExecError as exc:
            log.warning(
                "openclaw.cleanup_agent: list sessions failed for %s on %s: %s",
                agent.handle,
                host_exec.describe(device),
                exc,
            )
            return

        for session in sessions:
            key = session.get("key") or session.get("sessionKey")
            if not key:
                continue
            try:
                proc = host_exec.execute(
                    device,
                    [
                        "openclaw",
                        "gateway",
                        "call",
                        "sessions.reset",
                        "--params",
                        json.dumps({"key": key}),
                    ],
                    timeout=15.0,
                )
            except HostExecError as exc:
                log.warning(
                    "openclaw.cleanup_agent: reset dispatch failed (%s/%s): %s",
                    agent.handle,
                    key,
                    exc,
                )
                continue
            if proc.returncode != 0:
                log.warning(
                    "openclaw.cleanup_agent: reset failed (%s/%s): %s",
                    agent.handle,
                    key,
                    proc.stderr.strip()[:200],
                )

    # ── helpers ───────────────────────────────────────────────────────

    def _list_negotiation_sessions(
        self,
        device: Any,
        agent_handle: str,
    ) -> list[dict[str, Any]]:
        proc = host_exec.execute(
            device,
            [
                "openclaw",
                "sessions",
                "--agent",
                agent_handle,
                "--json",
                "--limit",
                "100",
            ],
            timeout=20.0,
        )
        if proc.returncode != 0 or not proc.stdout.strip():
            return []
        try:
            data = json.loads(proc.stdout)
        except json.JSONDecodeError:
            return []
        sessions = data if isinstance(data, list) else data.get("sessions", [])
        # Keep only sessions tied to mycelium-room / matrix channels
        # (matches the existing libs.openclaw filter).
        return [
            s
            for s in sessions
            if any(tag in (s.get("key") or s.get("sessionKey") or "") for tag in ("mycelium-room", "matrix:channel:"))
        ]


# ── module-level helpers ──────────────────────────────────────────────


def _matrix_token_env_for(handle: str) -> str:
    """Convention: agent ``alpha`` -> ``MATRIX_TOKEN_AGENT_ALPHA``."""
    suffix = handle.replace("-", "_").upper()
    return f"MATRIX_TOKEN_{suffix}"


def _seed_agent_for(device: Any) -> str | None:
    """Resolve the OpenClaw seed agent for ``device``.

    Per-host override comes from ``device.custom["openclaw_seed_agent"]``
    so testbed YAML can specify different pre-authed agents per box
    (lab boxes typically each have one auth'd seed: claire-agent on
    hub/spoke1, oclw5-agent on spoke2). Falls back to the global env
    var for environments where every host shares the same seed.
    """
    custom = getattr(device, "custom", None)
    if custom is not None:
        # ``custom`` may be a pyATS Custom mapping (.get) OR a plain
        # dict (test fixtures often use SimpleNamespace + dict). Try
        # both shapes so tests don't have to mimic pyATS's wrappers.
        if hasattr(custom, "get"):
            value = custom.get("openclaw_seed_agent")
            if value:
                return str(value)
    return os.environ.get(SEED_AGENT_ENV)


async def _send_matrix_dm(
    homeserver: str,
    token: str,
    room_id: str,
    body: str,
) -> None:
    """Send a single Matrix message via :class:`libs.matrix_client.MatrixClient`."""
    from libs.matrix_client import MatrixClient

    client = MatrixClient(homeserver=homeserver, access_token=token)
    try:
        await client.send_message(room_id, body)
    finally:
        await client.close()
