# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""The coordination board: room state projected into steerable rows.

The CLI carries its own copy of the projection rules — the thin ``uv tool`` CLI
can't import the frontend — so the words the two surfaces must agree on are
frozen in ``contracts/board-vocabulary.json`` and asserted from both sides.
"""

from mycelium.board.model import (
    KINDS,
    LENS_OF_STATUS,
    LENSES,
    PRIORITIES,
    STATUSES,
    VERBS,
    LiveItem,
    lens_of,
    priority_rank,
)
from mycelium.board.projection import project_items
from mycelium.board.schema import FieldSchema, infer_schema
from mycelium.board.upstream import UPSTREAM_STATES, attach_upstream

__all__ = [
    "KINDS",
    "LENSES",
    "LENS_OF_STATUS",
    "PRIORITIES",
    "STATUSES",
    "UPSTREAM_STATES",
    "VERBS",
    "FieldSchema",
    "attach_upstream",
    "LiveItem",
    "infer_schema",
    "lens_of",
    "priority_rank",
    "project_items",
]
