# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""Cross-channel consensus delivery.

When a :class:`route.NotifyHome` action fires, this module:
  1. Looks up each agent's stashed :class:`HomeAddress` in the shared
     :class:`return_address.ReturnAddressBook`.
  2. Resolves the corresponding platform adapter via the hermes
     ``gateway.platform_registry`` shared address book.
  3. Calls that adapter's ``send(chat_id, content, ...)`` so the
     consensus summary appears in the agent's original DM /
     Matrix room / Slack thread, *not* the Mycelium room they
     negotiated through.

The platform registry is hermes's own discovery point — same place the
gateway boots adapters from — so we never need to import a specific
platform module (Telegram, Discord, …) from the mycelium plugin. That
keeps the plugin honest about being a thin adapter rather than a
cross-cutting integration.

Best-effort: missing addresses, missing platform adapters, send
failures all log and continue. Consensus has already been reached by the
backend; the home delivery is an enhancement, not a correctness
requirement.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .return_address import ReturnAddressBook
    from .route import NotifyHome

logger = logging.getLogger(__name__)


async def deliver_notify_home(
    *,
    action: NotifyHome,
    addresses: ReturnAddressBook,
) -> None:
    """Send *action.consensus_summary* to each agent's home channel.

    Each delivery is independent — a failure to reach one agent's home
    never blocks the others.
    """
    try:
        from gateway.platform_registry import platform_registry
    except ImportError:  # pragma: no cover — hermes always exposes this
        logger.warning(
            "notify_home: gateway.platform_registry unavailable — skipping cross-channel delivery"
        )
        return

    for agent_id in action.agent_ids:
        home = addresses.lookup(session_room=action.session_room, agent_id=agent_id)
        if home is None:
            logger.debug(
                "notify_home: no return address for %s in %s — skipping",
                agent_id,
                action.session_room,
            )
            continue
        entry = platform_registry.get(home.platform) if hasattr(platform_registry, "get") else None
        adapter = _resolve_adapter_instance(entry)
        if adapter is None:
            logger.warning(
                "notify_home: no live adapter for platform %s (agent=%s) — skipping",
                home.platform,
                agent_id,
            )
            continue
        try:
            await adapter.send(
                chat_id=home.chat_id,
                content=action.consensus_summary,
                metadata={"thread_id": home.thread_id} if home.thread_id else None,
            )
        except Exception:  # noqa: BLE001 — never raise out of notify path
            logger.exception(
                "notify_home: %s.send failed for agent=%s chat=%s",
                home.platform,
                agent_id,
                home.chat_id,
            )

    # Consensus has been delivered everywhere we know about. Drop the
    # session's stash so a re-used session id can't replay home addresses
    # from a previous run.
    addresses.drop_session(action.session_room)


def _resolve_adapter_instance(entry):  # noqa: ANN001, ANN201
    """Best-effort extraction of a running adapter from a PlatformEntry.

    Hermes's :class:`gateway.platform_registry.PlatformEntry` carries
    factory + entry metadata; the *live* adapter instance is owned by the
    gateway runner. ``platform_registry.get()`` returns the entry; the
    GatewayRunner exposes ``platform_adapters`` keyed by name. We probe
    both locations defensively so the plugin works against a small
    surface change.
    """
    if entry is None:
        return None
    # PlatformEntry may carry the live adapter as ``instance`` on newer
    # hermes builds; older surface keeps it on the GatewayRunner only.
    inst = getattr(entry, "instance", None)
    if inst is not None:
        return inst
    try:
        from gateway.runner import gateway_runner  # type: ignore[import-not-found]
    except ImportError:
        return None
    adapters = getattr(gateway_runner, "platform_adapters", None)
    if not isinstance(adapters, dict):
        return None
    name = getattr(entry, "name", None)
    if not isinstance(name, str):
        return None
    return adapters.get(name)
