# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cisco Systems, Inc. and its affiliates

"""sstp/knowledge.py — KnowledgeMessage kind."""

from __future__ import annotations

from typing import Literal

from ._base import _STBaseMessage


class KnowledgeMessage(_STBaseMessage):
    """A knowledge assertion or belief update."""

    kind: Literal["knowledge"]
