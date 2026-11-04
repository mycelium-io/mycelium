# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""A git worktree of its own for an agent the runner launches with ``worktree``."""

from __future__ import annotations

import subprocess
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path


class WorktreeError(Exception):
    """A worktree that could not be made, with git's reason."""


def member_worktree(repo: Path, room: str, handle: str) -> Path:
    """A git worktree of ``repo`` for one agent, on a branch of its own.

    A worktree already at that path is used as it is, whatever branch it's on.
    """
    path = repo.parent / f"{repo.name}-{room}-{handle}"
    if path.exists():
        return path
    branch = f"agent/{room}/{handle}"
    proc = subprocess.run(  # noqa: S603 - arguments are code-built
        ["git", "-C", str(repo), "worktree", "add", "-b", branch, str(path)],  # noqa: S607
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        raise WorktreeError(f"could not create a worktree for @{handle}: {proc.stderr.strip()}")
    return path
