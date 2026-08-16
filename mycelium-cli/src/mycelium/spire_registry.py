# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""CLI-driven SPIRE workload registration for the appliance profile (#588).

When ``slim.identity=spire`` the shipped compose runs a co-located SPIRE
server+agent (see ``docker/compose.yml``). This module is the seam that makes
turning on attested identity *one switch*: ``mycelium agent create @alice``
registers the SVID entry against the running server, and ``mycelium agent rm
@alice`` revokes it — no hand-typed ``spire-server entry create``.

Every call shells out to ``docker compose exec`` against the compose project's
``spire-server`` service, reusing the same project/compose/env resolution the
rest of the lifecycle commands use. Nothing here mints keys — SPIRE owns the key
material; we only manage the *registration entry* that binds a workload selector
to ``spiffe://{trust_domain}/agent/{handle}`` (the same SPIFFE ID
``slim_identity.spiffe_id_for`` builds, so the backend's MLS provider and the
server's entry agree on the leaf).

The selector is the **backend container's** uid: in the server-held-membership
model the always-on backend is the co-located workload that fetches each
member's SVID (a resident spoke session can't be co-located — the #584 gotcha),
so an entry attested to the backend's uid is what lets the backend present
``@alice``'s identity. Every SPIRE call is best-effort: a failure is surfaced as
a warning, never a hard error, because the manifest is already written and the
agent still works on the PSK floor.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass, field

from mycelium.slim.identity import resolve_spire_trust_domain, spiffe_id_for

# The node SPIFFE ID the compose bootstrap binds the one-time join token to
# (``spiffe://{td}/agent-node``). Fixed on both sides so the workload-entry parent
# is deterministic — the registry never has to discover the attested agent node.
_AGENT_NODE_PATH = "agent-node"

# JWT-SVID TTL (seconds) for a member entry. Matches the server's short default;
# the provider re-fetches on expiry, so this is a refresh cadence, not a session cap.
_JWT_SVID_TTL_S = 300

# The compose service the SPIRE control-plane binary lives in.
_SPIRE_SERVER_SERVICE = "spire-server"
_BACKEND_SERVICE = "mycelium-backend"
_SPIRE_SERVER_BIN = "/opt/spire/bin/spire-server"


@dataclass
class SpireResult:
    """Outcome of a registry operation. ``ok`` gates the caller's success line."""

    ok: bool
    message: str
    spiffe_id: str | None = None
    entry_ids: list[str] = field(default_factory=list)


def _agent_node_id(trust_domain: str) -> str:
    return f"spiffe://{trust_domain}/{_AGENT_NODE_PATH}"


def _compose_exec(args: list[str], *, timeout: int = 20) -> subprocess.CompletedProcess[str]:
    """Run ``docker compose exec -T spire-server <args>`` in the compose project.

    Imports the lifecycle helpers lazily to avoid a module import cycle
    (``instance`` imports config which imports us in some paths).
    """
    from mycelium.commands.instance import _compose_base_cmd

    base = _compose_base_cmd()
    cmd = [*base, "exec", "-T", _SPIRE_SERVER_SERVICE, *args]
    return subprocess.run(cmd, capture_output=True, text=True, check=False, timeout=timeout)


def _backend_uid() -> str | None:
    """The uid the backend container runs as — the workload-attestor selector.

    Returns ``None`` if the backend isn't reachable; callers fall back to a
    documented warning rather than registering an entry with a wrong selector.
    """
    from mycelium.commands.instance import _compose_base_cmd

    base = _compose_base_cmd()
    try:
        result = subprocess.run(
            [*base, "exec", "-T", _BACKEND_SERVICE, "id", "-u"],
            capture_output=True,
            text=True,
            check=False,
            timeout=15,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    uid = result.stdout.strip()
    return uid if result.returncode == 0 and uid.isdigit() else None


def _entry_ids_for(spiffe_id: str, trust_domain: str) -> list[str]:
    """Entry IDs currently registered for ``spiffe_id`` (empty if none / server down)."""
    try:
        result = _compose_exec([_SPIRE_SERVER_BIN, "entry", "show", "-spiffeID", spiffe_id])
    except (OSError, subprocess.SubprocessError):
        return []
    if result.returncode != 0:
        return []
    ids: list[str] = []
    for line in result.stdout.splitlines():
        stripped = line.strip()
        # `entry show` prints `Entry ID         : <uuid>` blocks.
        if stripped.startswith("Entry ID"):
            _, _, value = stripped.partition(":")
            if value.strip():
                ids.append(value.strip())
    return ids


def register_workload(handle: str, trust_domain: str | None = None) -> SpireResult:
    """Register ``@handle`` as a SPIRE workload entry. Idempotent.

    Creates ``spiffe://{td}/agent/{handle}`` parented to the appliance's fixed
    agent node, selected by the backend container's uid. A pre-existing entry for
    the same SPIFFE ID short-circuits (no duplicate), so re-running ``agent
    create`` doesn't churn the datastore.
    """
    td = trust_domain or resolve_spire_trust_domain()
    spiffe_id = spiffe_id_for(handle, td)

    existing = _entry_ids_for(spiffe_id, td)
    if existing:
        return SpireResult(
            ok=True,
            message=f"already registered ({spiffe_id})",
            spiffe_id=spiffe_id,
            entry_ids=existing,
        )

    uid = _backend_uid()
    if uid is None:
        return SpireResult(
            ok=False,
            message=(
                "could not read the backend container's uid — is the stack up "
                "(mycelium up) with slim.identity=spire?"
            ),
            spiffe_id=spiffe_id,
        )

    try:
        result = _compose_exec(
            [
                _SPIRE_SERVER_BIN,
                "entry",
                "create",
                "-parentID",
                _agent_node_id(td),
                "-spiffeID",
                spiffe_id,
                "-selector",
                f"unix:uid:{uid}",
                "-jwtSVIDTTL",
                str(_JWT_SVID_TTL_S),
            ]
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return SpireResult(ok=False, message=f"registration failed: {exc}", spiffe_id=spiffe_id)

    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip().splitlines()
        hint = detail[-1] if detail else "spire-server entry create failed"
        return SpireResult(ok=False, message=hint, spiffe_id=spiffe_id)

    return SpireResult(
        ok=True,
        message=f"attested ({spiffe_id})",
        spiffe_id=spiffe_id,
        entry_ids=_entry_ids_for(spiffe_id, td),
    )


def revoke_workload(handle: str, trust_domain: str | None = None) -> SpireResult:
    """Delete every SPIRE entry for ``@handle``. Idempotent (no entry → ok).

    The inverse of :func:`register_workload`, wired into ``agent rm`` so removing
    an agent revokes its attested identity (ties to #590). Absent the server (spire
    off, or the stack down) this is a silent no-op — there is nothing to revoke.
    """
    td = trust_domain or resolve_spire_trust_domain()
    spiffe_id = spiffe_id_for(handle, td)

    entry_ids = _entry_ids_for(spiffe_id, td)
    if not entry_ids:
        return SpireResult(ok=True, message="no entry to revoke", spiffe_id=spiffe_id)

    revoked: list[str] = []
    for entry_id in entry_ids:
        try:
            result = _compose_exec([_SPIRE_SERVER_BIN, "entry", "delete", "-entryID", entry_id])
        except (OSError, subprocess.SubprocessError) as exc:
            return SpireResult(
                ok=False,
                message=f"revocation failed for {entry_id}: {exc}",
                spiffe_id=spiffe_id,
                entry_ids=revoked,
            )
        if result.returncode != 0:
            detail = (result.stderr or result.stdout or "").strip()
            return SpireResult(
                ok=False,
                message=f"could not delete entry {entry_id}: {detail}",
                spiffe_id=spiffe_id,
                entry_ids=revoked,
            )
        revoked.append(entry_id)

    return SpireResult(
        ok=True, message=f"revoked ({spiffe_id})", spiffe_id=spiffe_id, entry_ids=revoked
    )


def registered_handles(trust_domain: str | None = None) -> list[str] | None:
    """Handles with a live SPIRE entry, or ``None`` if the server is unreachable.

    ``doctor`` / ``/health`` render "SPIRE up, @alice attested" from this. ``None``
    (server down) is distinct from ``[]`` (server up, nothing registered) so a
    misconfig reads as a clear message, not an ambiguous empty list.
    """
    from mycelium.slim.identity import handle_from_spiffe_id

    td = trust_domain or resolve_spire_trust_domain()
    try:
        result = _compose_exec([_SPIRE_SERVER_BIN, "entry", "show"])
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0:
        return None

    handles: list[str] = []
    for line in result.stdout.splitlines():
        stripped = line.strip()
        if stripped.startswith("SPIFFE ID"):
            _, _, value = stripped.partition(":")
            handle = handle_from_spiffe_id(value.strip(), td)
            if handle:
                handles.append(handle)
    return sorted(set(handles))


def server_healthy() -> bool:
    """True if the SPIRE server answers a healthcheck in the compose project."""
    try:
        result = _compose_exec([_SPIRE_SERVER_BIN, "healthcheck"], timeout=15)
    except (OSError, subprocess.SubprocessError):
        return False
    return result.returncode == 0
