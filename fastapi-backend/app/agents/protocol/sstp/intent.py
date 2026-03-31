# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Julia Valenti

"""sstp/intent.py — IntentMessage kind."""

from __future__ import annotations

from typing import Literal

from ._base import _STBaseMessage


class IntentMessage(_STBaseMessage):
    """An agent expressing a goal or desired action."""

    kind: Literal["intent"]
