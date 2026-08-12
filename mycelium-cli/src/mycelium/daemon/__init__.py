# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""
Mycelium agent daemon — the userlevel dispatcher for cold-spawn agents.

Subscribes to room SSE for rooms configured in ``~/.mycelium/daemon.toml``,
watches for ``@handle`` mentions of agents registered under ``agents/<handle>``,
and dispatches them via ``claude -p`` with the agent's notes as system prompt.
Logs every invocation to ``agents/<handle>/log/<ts>`` and posts the reply back
to the originating room as ``@handle``.

This package is invoked as ``python -m mycelium.daemon`` by the system service
unit installed via ``mycelium adapter add claude-code --step=daemon``.
"""

from mycelium.daemon.config import DaemonConfig, daemon_config_path
from mycelium.daemon.state import DaemonState

__all__ = ["DaemonConfig", "DaemonState", "daemon_config_path"]
