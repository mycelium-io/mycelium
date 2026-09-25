# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""A room's repository on the hub, and each worker's worktree of it."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from app.services import workspace


def _git(cwd: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=cwd, capture_output=True, text=True, check=True
    ).stdout.strip()


@pytest.fixture
def upstream(tmp_path: Path) -> Path:
    repo = tmp_path / "upstream"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "trunk")
    (repo / "README.md").write_text("hello\n")
    _git(repo, "add", ".")
    _git(repo, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "first")
    return repo


def test_a_room_with_no_repository_gets_an_empty_one():
    shared = workspace.prepare("empty-room")

    assert (shared / ".git").exists()
    assert _git(shared, "rev-parse", "--abbrev-ref", "HEAD") == "main"
    assert workspace.origin_of("empty-room") is None


def test_each_member_gets_its_own_worktree_and_branch(upstream: Path):
    workspace.prepare("clone-room", str(upstream))

    one = workspace.checkout_for("clone-room", "agent-1")
    two = workspace.checkout_for("clone-room", "agent-2")

    assert one.path != two.path
    assert (one.path / "README.md").read_text() == "hello\n"
    assert _git(one.path, "rev-parse", "--abbrev-ref", "HEAD") == "swarm/agent-1"
    assert one.base == "trunk"
    assert one.origin == str(upstream)
    assert "swarm/agent-1" in one.describe()
    # Asking again is the same checkout, not a second one.
    assert workspace.checkout_for("clone-room", "agent-1") == one


def test_a_member_can_read_a_teammates_branch(upstream: Path):
    workspace.prepare("shared-room", str(upstream))
    one = workspace.checkout_for("shared-room", "agent-1")
    two = workspace.checkout_for("shared-room", "agent-2")
    (one.path / "part.txt").write_text("mine\n")
    _git(one.path, "add", ".")
    subprocess.run(
        ["git", "commit", "-qm", "part"],
        cwd=one.path,
        check=True,
        env={**workspace.identity("agent-1"), "PATH": "/usr/bin:/bin:/usr/local/bin"},
    )

    assert _git(two.path, "log", "-1", "--format=%an", "swarm/agent-1") == "agent-1"


def test_a_room_keeps_the_repository_it_started_on(upstream: Path, tmp_path: Path):
    workspace.prepare("one-repo", str(upstream))

    with pytest.raises(workspace.WorkspaceError, match="already works on"):
        workspace.prepare("one-repo", str(tmp_path / "elsewhere"))
    # The same repository again is fine.
    workspace.prepare("one-repo", str(upstream))


@pytest.mark.parametrize(
    "repo",
    ["", "relative/path", "--upload-pack=touch /tmp/x", "ext::sh -c touch% /tmp/x", "ftp://x/y"],
)
def test_only_urls_and_hub_paths_are_cloned(repo: str):
    assert not workspace.valid_repo(repo)
    with pytest.raises(workspace.WorkspaceError, match="not a repository"):
        workspace.prepare("bad-room", repo or " x")


@pytest.mark.parametrize(
    "repo",
    [
        "https://github.com/org/repo.git",
        "git@github.com:org/repo.git",
        "ssh://git@host/r",
        "/srv/r",
    ],
)
def test_the_usual_repository_forms_are_accepted(repo: str):
    assert workspace.valid_repo(repo)


def test_a_repository_that_cannot_be_cloned_says_so(tmp_path: Path):
    with pytest.raises(workspace.WorkspaceError, match="git clone failed"):
        workspace.prepare("missing-room", str(tmp_path / "nothing-here"))
