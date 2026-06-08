# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""Hermes-side entry point for the Mycelium platform plugin.

Hermes calls ``register(ctx)`` once at gateway boot, before any platform
adapter is instantiated. We use the ``PluginContext.register_platform``
API documented in ``hermes_cli/plugins.py`` to slot the
:class:`MyceliumRoomAdapter` factory into ``gateway.platform_registry``
next to ``matrix.py`` / ``slack.py`` / etc. The gateway then walks the
``platforms`` block of ``config.yaml`` and constructs an adapter for any
that have ``enabled: true``.

Logging is via the standard library ``logging`` module — hermes is the
host, so we use whatever logger it wires up by default.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def register(ctx) -> None:  # noqa: ANN001 — ctx is hermes-typed
    """Hermes plugin entry point.

    Lazy-imports the adapter module so plugin import is cheap when only
    metadata is being read (``hermes plugins list``).
    """
    from .adapter import MyceliumRoomAdapter
    from .return_address import on_pre_gateway_dispatch

    ctx.register_platform(
        name="mycelium-room",
        label="Mycelium",
        adapter_factory=MyceliumRoomAdapter,
        check_fn=_dependency_check,
        platform_hint=(
            "Mycelium coordination rooms (multi-agent negotiation + persistent memory)."
        ),
        emoji="🌿",
    )
    ctx.register_hook("pre_gateway_dispatch", on_pre_gateway_dispatch)
    logger.info("mycelium-room platform registered (with return-origin hook)")


def _dependency_check() -> bool:
    """Return True iff the adapter can be safely instantiated.

    The adapter uses ``aiohttp`` for SSE + outbound POST. ``aiohttp`` is
    already a hermes hard dependency (webhook adapter), so this is mostly
    a forward-looking guard.
    """
    try:
        import aiohttp  # noqa: F401  — probe-only
    except ImportError:
        logger.warning("aiohttp not available — mycelium-room platform disabled")
        return False
    return True
