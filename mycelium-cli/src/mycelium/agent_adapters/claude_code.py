# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Julia Valenti

"""Back-compat shim — see ``mycelium.integrations.claude_code``."""

from __future__ import annotations

from mycelium.integrations.claude_code import ClaudeCodeAdapter, ClaudeCodeIntegration

__all__ = ["ClaudeCodeAdapter", "ClaudeCodeIntegration"]
