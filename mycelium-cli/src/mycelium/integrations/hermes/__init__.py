# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""Hermes integration — long-lived-gateway dispatch via a hermes-side plugin.

Hermes runs as a single long-lived process (`hermes gateway run`) that owns
its own platform adapters (Matrix, Slack, Discord, …). The Mycelium plugin
shipped under ``assets/mycelium/plugin/`` registers an additional
``mycelium-room`` platform adapter using hermes's native plugin API (see
``hermes_cli/plugins.py:PluginContext.register_platform``), so a Mycelium
room becomes just another messaging channel the gateway dispatches to.

This package is the mycelium-side bookkeeping: it stages the plugin onto the
host, patches ``~/.hermes/config.yaml``, and registers handle→room fan-out
entries. The plugin itself is what subscribes to room SSE, formats ticks,
posts replies, and notifies home — symmetric to OpenClaw's TypeScript
``mycelium-room`` channel plugin, just in Python.
"""

from __future__ import annotations

from mycelium.integrations.hermes.dispatch import (
    HermesAdapter,
    HermesError,
    HermesIntegration,
)

__all__ = ["HermesAdapter", "HermesError", "HermesIntegration"]
