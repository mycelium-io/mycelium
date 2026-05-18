# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Julia Valenti

"""Back-compat shim. The agent-adapter OOP layer moved to
``mycelium.integrations`` (which now also owns the install facet — one
contract per runtime family, closing #173). Import from there instead; this
module re-exports for any out-of-tree caller and will be removed in a later
release.
"""

from __future__ import annotations

from mycelium.integrations import AddOptions, AgentAdapter, get_adapter

__all__ = ["AddOptions", "AgentAdapter", "get_adapter"]
