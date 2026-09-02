# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""The coordination board: room state projected into steerable rows.

The CLI carries its own copy of the projection rules — the thin ``uv tool`` CLI
can't import the frontend — so the words the two surfaces must agree on are
frozen in ``contracts/board-vocabulary.json`` and asserted from both sides.
"""

from mycelium.board import assignment
from mycelium.board.assignment import assignment_of, attention_of_item
from mycelium.board.model import (
    ATTENTION_FILTERS,
    ATTENTION_OF_STATUS,
    KINDS,
    PRIORITIES,
    ROW_ACTIONS,
    STATUSES,
    LiveItem,
    attention_of_status,
    priority_rank,
)
from mycelium.board.projection import project_items
from mycelium.board.schema import FieldSchema, infer_schema
from mycelium.board.upstream import UPSTREAM_STATES, attach_upstream

__all__ = [
    "KINDS",
    "ATTENTION_FILTERS",
    "ATTENTION_OF_STATUS",
    "PRIORITIES",
    "STATUSES",
    "UPSTREAM_STATES",
    "ROW_ACTIONS",
    "FieldSchema",
    "attach_upstream",
    "assignment",
    "assignment_of",
    "LiveItem",
    "infer_schema",
    "attention_of_status",
    "attention_of_item",
    "priority_rank",
    "project_items",
]
