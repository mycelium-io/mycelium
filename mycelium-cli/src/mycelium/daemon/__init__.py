# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""
Mycelium Claude Code daemon — the userlevel mirror of the OpenClaw gateway.

Subscribes to room SSE for rooms configured in ``~/.mycelium/cc-daemon.toml``,
watches for ``@handle`` mentions of agents registered under ``agents/<handle>``,
and dispatches them via ``claude -p`` with the agent's notes as system prompt.
Logs every invocation to ``agents/<handle>/log/<ts>`` and posts the reply back
to the originating room as ``@handle``.

Architectural symmetry:

        Mycelium room (SSE)
                │
        ┌───────┴────────┐
 OpenClaw gateway   mycelium-cc-daemon
   (TS, existing)     (Python, this)
        │                │
   openclaw            claude -p
   agents              spawns (cold)

This package is invoked as ``python -m mycelium.daemon`` by the system service
unit installed via ``mycelium adapter add claude-code --step=daemon``.
"""

from mycelium.daemon.config import DaemonConfig, daemon_config_path
from mycelium.daemon.state import DaemonState

__all__ = ["DaemonConfig", "DaemonState", "daemon_config_path"]
