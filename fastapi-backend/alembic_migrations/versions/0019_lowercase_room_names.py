# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""Normalize room names to lowercase.

Room names are used as DB keys, filesystem paths (.mycelium/rooms/{name}/),
and as the room segment in OpenClaw session keys (which always lowercase the
name). Without normalization, ``MyRoom`` (DB) and ``myroom`` (session key)
refer to the same room on macOS (case-insensitive FS) but not on Linux, and
GET /rooms/myroom 404s against the ``MyRoom`` row.

This migration lowercases all existing room names in the DB and renames the
corresponding filesystem directories. If two rooms would collide after
lowercasing (e.g. ``MyRoom`` and ``myroom``), the migration aborts with a
descriptive error rather than silently clobbering data.

Revision ID: 0019
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

import sqlalchemy as sa
from alembic import op

revision = "0019"
down_revision = "0018"
branch_labels = None
depends_on = None

logger = logging.getLogger(__name__)


def _data_dir() -> Path:
    data_dir = os.environ.get("MYCELIUM_DATA_DIR") or str(Path.home() / ".mycelium")
    return Path(data_dir)


def upgrade() -> None:
    conn = op.get_bind()

    # Fetch all room names that contain uppercase letters.
    rows = conn.execute(sa.text("SELECT id, name FROM rooms WHERE name != lower(name)")).fetchall()

    if rows:
        # Check for collisions before making any changes. A collision is any case
        # where two distinct existing room names collapse to the same lowercase value
        # (e.g. an existing lowercase 'myroom' plus 'MyRoom', or two mixed-case
        # 'MyRoom' and 'MYROOM'). Either would violate the rooms.name unique
        # constraint once lowercased, so abort with a descriptive error.
        existing = [r[0] for r in conn.execute(sa.text("SELECT name FROM rooms")).fetchall()]
        by_lower: dict[str, list[str]] = {}
        for name in existing:
            by_lower.setdefault(name.lower(), []).append(name)
        for lower, names in by_lower.items():
            if len(names) > 1:
                conflict = ", ".join(sorted(f"'{n}'" for n in names))
                raise RuntimeError(
                    f"0019: cannot lowercase rooms {conflict} → '{lower}': they would "
                    f"collide on the same name. Resolve the conflict manually."
                )

        # Rename the filesystem directories first.
        # If a rename fails for a room that has data on disk, skip that room's DB
        # update too — leaving DB and FS out of sync would cause memory read/write
        # misses and is worse than leaving both in the original state.
        rooms_dir = _data_dir() / "rooms"
        fs_rename_failed: set[str] = set()
        for _room_id, old_name in rows:
            new_name = old_name.lower()
            if new_name == old_name:
                continue
            old_dir = rooms_dir / old_name
            new_dir = rooms_dir / new_name
            if old_dir.exists() and not new_dir.exists():
                try:
                    old_dir.rename(new_dir)
                    logger.info("0019: renamed directory %s → %s", old_dir, new_dir)
                except OSError as exc:
                    logger.warning(
                        "0019: could not rename %s → %s: %s — skipping DB update for '%s'",
                        old_dir,
                        new_dir,
                        exc,
                        old_name,
                    )
                    fs_rename_failed.add(old_name)
            elif old_dir.exists() and new_dir.exists():
                # Orphaned lowercase directory already on disk (e.g. from a prior
                # volume wipe) — renaming would silently overwrite it. Skip the DB
                # update too so the DB and FS stay consistent.
                logger.warning(
                    "0019: cannot rename %s → %s: target already exists — skipping DB update for '%s'",
                    old_dir,
                    new_dir,
                    old_name,
                )
                fs_rename_failed.add(old_name)

        if fs_rename_failed:
            # Only lowercase rooms whose FS rename succeeded (or had no data directory).
            # Rooms that failed FS rename are excluded to keep DB and FS in sync.
            safe_rows = [
                (room_id, old_name)
                for room_id, old_name in rows
                if old_name not in fs_rename_failed
            ]
            for room_id, _old_name in safe_rows:
                conn.execute(
                    sa.text(
                        "UPDATE rooms SET name = lower(name) WHERE id = :id AND name != lower(name)"
                    ),
                    {"id": room_id},
                )
            skipped = len(rows) - len(safe_rows)
            logger.warning(
                "0019: skipped DB update for %d room(s) due to FS rename failure: %s",
                skipped,
                ", ".join(sorted(fs_rename_failed)),
            )
        else:
            conn.execute(sa.text("UPDATE rooms SET name = lower(name) WHERE name != lower(name)"))

        logger.info("0019: lowercased %d room name(s)", len(rows) - len(fs_rename_failed))
    else:
        logger.info("0019: no mixed-case room names found; applying FK schema changes only")

    # ── Add ON UPDATE CASCADE to every FK pointing at rooms(name) ─────────
    # Always runs, regardless of whether any rooms needed lowercasing. Fresh
    # installs have no mixed-case rows but still need the correct FK semantics
    # that models.py declares (onupdate="CASCADE"). Without this, any future
    # room-name update (e.g. a rename migration) hits a FK violation on
    # instances that were never through the data-migration path.
    fk_rows = conn.execute(
        sa.text(
            """
            SELECT tc.constraint_name, tc.table_name, kcu.column_name
            FROM information_schema.table_constraints AS tc
            JOIN information_schema.key_column_usage AS kcu
              ON tc.constraint_name = kcu.constraint_name
             AND tc.table_schema = kcu.table_schema
            JOIN information_schema.constraint_column_usage AS ccu
              ON tc.constraint_name = ccu.constraint_name
             AND tc.table_schema = ccu.table_schema
            WHERE tc.constraint_type = 'FOREIGN KEY'
              AND ccu.table_name = 'rooms'
              AND ccu.column_name = 'name'
            """
        )
    ).fetchall()

    for constraint_name, table_name, column_name in fk_rows:
        op.drop_constraint(constraint_name, table_name, type_="foreignkey")
        op.create_foreign_key(
            constraint_name,
            table_name,
            "rooms",
            [column_name],
            ["name"],
            ondelete="CASCADE",
            onupdate="CASCADE",
        )


def downgrade() -> None:
    # Intentionally a no-op: there is no safe way to reverse case normalization
    # once the filesystem directories have been renamed and clients have stored
    # the lowercase names.
    logger.warning("0019: downgrade is a no-op — room names remain lowercase")
