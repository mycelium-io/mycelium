# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Julia Valenti

"""Back-compat shim — see ``mycelium.integrations.base``."""

from __future__ import annotations

from mycelium.integrations.base import AddOptions, AgentAdapter, Integration

__all__ = ["AddOptions", "AgentAdapter", "Integration"]
