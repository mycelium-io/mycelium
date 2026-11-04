# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""An agent launched with ``worktree`` gets a git worktree of its own, beside the repository."""

from __future__ import annotations

import subprocess
from typing import TYPE_CHECKING

import pytest

from mycelium.runner.worktrees import WorktreeError, member_worktree

if TYPE_CHECKING:
    from pathlib import Path


def _git(*args: str) -> str:
    return subprocess.run(  # noqa: S603
        ["git", *args],  # noqa: S607
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()


def _repo(tmp_path: Path) -> Path:
    repo = tmp_path / "api"
    repo.mkdir()
    _git("init", "-q", str(repo))
    _git(
        "-C",
        str(repo),
        "-c",
        "user.name=t",
        "-c",
        "user.email=t@example.com",
        "commit",
        "-q",
        "--allow-empty",
        "-m",
        "init",
    )
    return repo


def test_each_agent_gets_a_worktree_on_a_branch_of_its_own(tmp_path: Path):
    tree = member_worktree(_repo(tmp_path), "eng", "scout")
    assert tree == tmp_path / "api-eng-scout"
    assert _git("-C", str(tree), "branch", "--show-current") == "agent/eng/scout"


def test_a_worktree_already_there_is_used_as_it_is(tmp_path: Path):
    repo = _repo(tmp_path)
    # One an older version made, on the branch name it used: kept, not made again.
    old = tmp_path / "api-eng-scout"
    _git("-C", str(repo), "worktree", "add", "-q", "-b", "older/eng/scout", str(old))
    assert member_worktree(repo, "eng", "scout") == old
    assert _git("-C", str(old), "branch", "--show-current") == "older/eng/scout"


def test_a_folder_that_isnt_a_repository_is_refused(tmp_path: Path):
    plain = tmp_path / "plain"
    plain.mkdir()
    with pytest.raises(WorktreeError, match="could not create a worktree for @scout"):
        member_worktree(plain, "eng", "scout")
