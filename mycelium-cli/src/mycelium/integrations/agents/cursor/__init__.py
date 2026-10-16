# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""Cursor Agent: a CLI whose agents get a workspace rule and an AGENTS.md section."""

from __future__ import annotations

from mycelium.integrations.agents.cursor.dispatch import Cursor, CursorIntegration

__all__ = ["Cursor", "CursorIntegration"]
