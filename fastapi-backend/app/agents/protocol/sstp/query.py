# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cisco Systems, Inc. and its affiliates

"""sstp/query.py — QueryMessage kind."""

from __future__ import annotations

from typing import Literal

from ._base import _STBaseMessage


class QueryMessage(_STBaseMessage):
    """A question directed at an agent, memory node, or service."""

    kind: Literal["query"]
