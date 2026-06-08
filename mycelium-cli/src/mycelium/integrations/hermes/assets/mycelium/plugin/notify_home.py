# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""Cross-channel consensus delivery.

When a :class:`route.NotifyHome` action fires, this module:
  1. Looks up each agent's stashed :class:`HomeAddress` in the shared
     :class:`return_address.ReturnAddressBook`.
  2. Resolves the live platform adapter via the running
     :class:`gateway.run.GatewayRunner` (same path as
     ``tools/send_message_tool``).
  3. Calls that adapter's ``send(chat_id, content, ...)`` so the
     consensus summary appears in the agent's original DM /
     Matrix room / Slack thread, *not* the Mycelium room they
     negotiated through.

Best-effort: missing addresses, missing adapters, send failures all log
and continue. Consensus has already been reached by the backend.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .return_address import ReturnAddressBook
    from .route import NotifyHome

logger = logging.getLogger(__name__)


async def deliver_notify_home(
    *,
    action: NotifyHome,
    addresses: ReturnAddressBook,
) -> None:
    """Send *action.consensus_summary* to each agent's home channel."""
    for agent_id in action.agent_ids:
        home = addresses.lookup(session_room=action.session_room, agent_id=agent_id)
        if home is None:
            logger.debug(
                "notify_home: no return address for %s in %s — skipping",
                agent_id,
                action.session_room,
            )
            continue
        adapter = _resolve_live_adapter(home.platform)
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
            logger.info(
                "notify_home → %s on %s:%s",
                agent_id,
                home.platform,
                home.chat_id,
            )
        except Exception:  # noqa: BLE001 — never raise out of notify path
            logger.exception(
                "notify_home: %s.send failed for agent=%s chat=%s",
                home.platform,
                agent_id,
                home.chat_id,
            )

    addresses.drop_session(action.session_room)


def _resolve_live_adapter(platform_name: str) -> Any | None:
    """Return the in-process adapter for *platform_name*, if the gateway is up."""
    try:
        from gateway.config import Platform
        from gateway.run import _gateway_runner_ref
    except ImportError:
        logger.warning(
            "notify_home: gateway imports unavailable — skipping cross-channel delivery",
        )
        return None

    runner = _gateway_runner_ref()
    if runner is None:
        return None

    adapters = getattr(runner, "adapters", None)
    if not isinstance(adapters, dict):
        return None

    try:
        platform = Platform(platform_name)
    except ValueError:
        logger.warning("notify_home: unknown platform name %r", platform_name)
        return None

    return adapters.get(platform)
