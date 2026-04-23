# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cisco Systems, Inc. and its affiliates

"""Room utilities for Mycelium CLI."""

from mycelium.config import MyceliumConfig
from mycelium.exceptions import MyceliumError


def ensure_room_set(
    config: MyceliumConfig,
    room_override: str | None = None,
) -> str:
    """
    Ensure a room is set.

    Returns the active room name or raises if none is set.
    """
    active_room = config.get_active_room()

    if room_override is not None:
        if room_override.strip() == "":
            raise MyceliumError(
                "Empty room name not allowed",
                suggestion="Run 'mycelium room use <room-name>' to set your active room",
            )
        target_room = room_override
    elif active_room:
        target_room = active_room
    else:
        raise MyceliumError(
            "No room set",
            suggestion="Run 'mycelium room use <room-name>' first",
        )

    if target_room != active_room:
        import typer

        if active_room:
            typer.secho(f"Switching room: {active_room} → {target_room}", dim=True)
        else:
            typer.secho(f"Setting room: {target_room}", dim=True)
        config.init_project(room_name=target_room)
        config.save()

    return target_room
