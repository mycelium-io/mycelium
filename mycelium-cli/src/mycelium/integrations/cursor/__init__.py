# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Julia Valenti

"""Cursor integration — cc-daemon dispatch (cold spawn ``cursor-agent -p``)."""

from __future__ import annotations

from mycelium.integrations.cursor.dispatch import CursorAdapter, CursorIntegration

__all__ = ["CursorAdapter", "CursorIntegration"]
