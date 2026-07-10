"""Fixed agent pools per device + adapter for the scenario matrix.

Scenario rows declare logical **roles**; pools map each role to a
runtime **handle** (``agent-alpha``, ``claire-agent``, …) and list
every slot that must exist on a host before scenarios run.
"""

from __future__ import annotations

import logging
import time
from typing import Any

from libs.host_exec import HostExecError
from libs.provisioners import AgentRef, PrereqMissing, get_provisioner

log = logging.getLogger(__name__)

# Mirrors infra/scripts/spoke-entrypoint.sh + scenarios.yaml role usage.
DEFAULT_AGENT_POOLS: dict[str, dict[str, dict[str, Any]]] = {
    "hub": {
        "openclaw": {
            "slots": ["agent-alpha", "agent-beta", "agent-gamma", "agent-delta"],
            "roles": {
                "alpha": "agent-alpha",
                "beta": "agent-beta",
                "gamma": "agent-gamma",
                "delta": "agent-delta",
                "planner": "agent-gamma",
                "lawyer-a": "agent-alpha",
                "lawyer-b": "agent-beta",
            },
        },
        "hermes": {
            "slots": ["alpha-he", "beta-he", "gamma-he"],
            "roles": {
                "alpha-he": "alpha-he",
                "beta-he": "beta-he",
                "gamma-he": "gamma-he",
            },
        },
        "cursor": {
            "slots": [],
            "roles": {
                "alpha-cu": "alpha-cu",
                "beta-cu": "beta-cu",
                "front-cu": "front-cu",
            },
        },
    },
    "spoke1": {
        "openclaw": {
            "slots": ["claire-agent"],
            "roles": {
                "beta": "claire-agent",
                "lawyer-b": "claire-agent",
            },
        },
        "hermes": {
            "slots": ["beta-he"],
            "roles": {
                "beta-he": "beta-he",
                "back-he": "beta-he",
            },
        },
        "cursor": {
            "slots": [],
            "roles": {
                "designer": "designer",
                "beta-cu": "beta-cu",
            },
        },
    },
    "spoke2": {
        "openclaw": {
            "slots": ["oclw5-agent"],
            "roles": {
                "gamma": "oclw5-agent",
            },
        },
        "hermes": {
            "slots": ["gamma-he"],
            "roles": {
                "gamma-he": "gamma-he",
                "ops": "gamma-he",
            },
        },
        "cursor": {
            "slots": [],
            "roles": {
                "ops": "ops",
            },
        },
    },
}


def load_agent_pools(parameters: dict[str, Any] | None) -> dict[str, dict[str, dict[str, Any]]]:
    """Return agent pools from datafile parameters, else built-in defaults."""
    if not parameters:
        return DEFAULT_AGENT_POOLS
    custom = parameters.get("agent_pools")
    if not custom:
        return DEFAULT_AGENT_POOLS
    return _normalize_pools(custom)


def _normalize_pools(raw: dict[str, Any]) -> dict[str, dict[str, dict[str, Any]]]:
    out: dict[str, dict[str, dict[str, Any]]] = {}
    for host, adapters in raw.items():
        if not isinstance(adapters, dict):
            continue
        out[host] = {}
        for adapter, cfg in adapters.items():
            if not isinstance(cfg, dict):
                continue
            slots = list(cfg.get("slots") or [])
            roles = dict(cfg.get("roles") or {})
            out[host][adapter] = {"slots": slots, "roles": roles}
    return out


def adapter_hosts_from_wants(wants: set[tuple[str, str, str]]) -> set[tuple[str, str]]:
    return {(adapter, host) for adapter, _, host in wants}


def pool_slots(
    pools: dict[str, dict[str, dict[str, Any]]],
    host: str,
    adapter: str,
) -> list[str]:
    host_pools = pools.get(host) or {}
    adapter_pool = host_pools.get(adapter) or {}
    return list(adapter_pool.get("slots") or [])


def resolve_role_handle(
    role: str,
    adapter: str,
    host: str,
    pools: dict[str, dict[str, dict[str, Any]]],
) -> str:
    """Map a scenario role to the runtime handle for ``adapter`` on ``host``."""
    host_pools = pools.get(host) or {}
    adapter_pool = host_pools.get(adapter) or {}
    roles = adapter_pool.get("roles") or {}
    if role in roles:
        return str(roles[role])
    # Hermes/cursor roles are usually identity handles; openclaw should be explicit.
    if adapter in {"hermes", "cursor"}:
        return role
    raise KeyError(f"no pool mapping for role {role!r} ({adapter}@{host})")


def ensure_pool_slots(
    testbed: Any,
    wants: set[tuple[str, str, str]],
    pools: dict[str, dict[str, dict[str, Any]]],
) -> list[str]:
    """Ensure every configured slot exists for adapters used by ``wants``."""
    failures: list[str] = []
    for adapter, host in sorted(adapter_hosts_from_wants(wants)):
        slots = pool_slots(pools, host, adapter)
        if not slots:
            continue
        device = testbed.devices.get(host)
        if device is None:
            failures.append(f"{adapter}@{host}: testbed has no device named {host!r}")
            continue
        try:
            provisioner = get_provisioner(adapter)
            provisioner.check_prereqs(device)
        except (KeyError, PrereqMissing, HostExecError) as exc:
            failures.append(f"{adapter}@{host}: pool prereq — {exc}")
            continue

        try:
            discovered = {r.handle for r in provisioner.discover_available(device)}
        except Exception as exc:  # noqa: BLE001 - discovery is best-effort
            log.warning("ensure_pool_slots: discover_available(%s, %s) failed: %s", adapter, host, exc)
            discovered = set()

        for slot in slots:
            if slot in discovered:
                log.debug("  pool slot %s already present on %s/%s", slot, adapter, host)
                continue
            last_exc: Exception | None = None
            for attempt in range(2):
                try:
                    provisioner.ensure_runtime(device, slot)
                    log.info("  ✓ ensured pool slot %s (%s@%s)", slot, adapter, host)
                    last_exc = None
                    break
                except (PrereqMissing, HostExecError) as exc:
                    last_exc = exc
                    if attempt == 0 and "connect" in str(exc).lower():
                        log.warning(
                            "  ⚠ pool slot %s/%s/%s connect error, retrying in 5s…",
                            adapter,
                            host,
                            slot,
                        )
                        time.sleep(5)
            if last_exc is not None:
                failures.append(f"{slot}@{host} ({adapter}): ensure_runtime — {last_exc}")
    return failures


def provision_roles_for_wants(
    testbed: Any,
    wants: set[tuple[str, str, str]],
    pools: dict[str, dict[str, dict[str, Any]]],
) -> tuple[dict[tuple[str, str, str], AgentRef], list[str]]:
    """Resolve each wanted role to a pool handle and return ``AgentRef`` map."""
    provisioned: dict[tuple[str, str, str], AgentRef] = {}
    failures: list[str] = []

    discovered_index: dict[tuple[str, str], dict[str, AgentRef]] = {}
    for adapter, host in sorted(adapter_hosts_from_wants(wants)):
        device = testbed.devices.get(host)
        if device is None:
            continue
        try:
            provisioner = get_provisioner(adapter)
            refs = provisioner.discover_available(device)
        except Exception:  # noqa: BLE001 - fall through to ensure_runtime per role
            refs = []
        discovered_index[(adapter, host)] = {r.handle: r for r in refs}

    for adapter, role, host in sorted(wants):
        device = testbed.devices.get(host)
        if device is None:
            failures.append(f"{role}@{host}: testbed has no device named {host!r}")
            continue
        try:
            provisioner = get_provisioner(adapter)
        except KeyError as exc:
            failures.append(f"{role}@{host}: {exc}")
            continue

        try:
            provisioner.check_prereqs(device)
        except (PrereqMissing, HostExecError) as exc:
            failures.append(f"{role}@{host} ({adapter}): prereq missing — {exc}")
            continue

        try:
            target_handle = resolve_role_handle(role, adapter, host, pools)
        except KeyError as exc:
            failures.append(f"{role}@{host} ({adapter}): {exc}")
            continue

        by_handle = discovered_index.get((adapter, host), {})
        if target_handle in by_handle:
            ref = by_handle[target_handle]
            log.info(
                "  ✓ %s/%s on %s → %r (pool slot)",
                adapter,
                role,
                host,
                ref.handle,
            )
        else:
            try:
                ref = provisioner.ensure_runtime(device, target_handle)
            except PrereqMissing as exc:
                failures.append(f"{role}@{host} ({adapter}): ensure_runtime — {exc}")
                continue
            except HostExecError as exc:
                failures.append(f"{role}@{host} ({adapter}): transport — {exc}")
                continue
            log.info(
                "  ✓ %s/%s on %s → %r (ensured)",
                adapter,
                role,
                host,
                ref.handle,
            )

        provisioned[(adapter, role, host)] = ref

    return provisioned, failures


def reset_openclaw_pools_for_wants(
    testbed: Any,
    wants: set[tuple[str, str, str]],
    pools: dict[str, dict[str, dict[str, Any]]],
    *,
    idle_wait_seconds: int | None = None,
) -> None:
    """Reset only the openclaw handles used by ``wants`` on each host.

    Clears stale parent-room session state left by prior scenario rows.
    Previously reset the full pool slot list (all hub agents); now scoped
    to only the roles actually used in this scenario so idle agents are
    not penalised with unnecessary gateway resets.
    """
    # Build per-host set of handles to reset (only openclaw roles in wants).
    host_handles: dict[str, set[str]] = {}
    for adapter, role, host in wants:
        if adapter != "openclaw":
            continue
        try:
            handle = resolve_role_handle(role, adapter, host, pools)
        except KeyError:
            # Role not in pool — fall back to full slot list for this host.
            handle = None
        if handle:
            host_handles.setdefault(host, set()).add(handle)
        else:
            # Unknown role: reset entire pool for safety.
            host_handles[host] = set(pool_slots(pools, host, adapter))

    for host, handles in sorted(host_handles.items()):
        if not handles:
            continue
        device = testbed.devices.get(host)
        if device is None:
            continue
        try:
            provisioner = get_provisioner("openclaw")
            reset = getattr(provisioner, "reset_device_gateway_sessions", None)
            if callable(reset):
                reset(device, handles=sorted(handles), idle_wait_seconds=idle_wait_seconds)
            else:
                log.warning("reset_openclaw_pools_for_wants: no reset on %s", host)
        except Exception as exc:  # noqa: BLE001 - hygiene is best-effort
            log.warning("reset_openclaw_pools_for_wants: %s@%s failed: %s", "openclaw", host, exc)
