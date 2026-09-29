# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""Where a worker's tools work: a checkout on the hub, one per member.

A room that runs workers has one repository on the hub, at
``<data dir>/workspaces/<room>/repo``: a clone of the repository its swarm was
started on, or an empty one when it was given none. Each worker works in its
own git worktree of it (``<room>/<handle>``, on branch ``swarm/<handle>``), so
two members editing at once never share a checkout, and every part's work is a
branch the others can read, review and merge from their own.

The workspace lives under the data dir, beside ``rooms/``, so on a hub run by
``mycelium up`` it is on the host too (``~/.mycelium/workspaces``) and can be
opened there. It is state the hub keeps, like the memory files, not a memory.

Every call here is blocking git; callers run them off the event loop.
"""

from __future__ import annotations

import logging
import os
import re
import subprocess
import threading
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

#: The directory under the data dir that holds every room's workspace.
WORKSPACES = "workspaces"
#: The shared repository inside a room's workspace.
REPO = "repo"
#: A member's branch is this prefix plus its handle.
BRANCH_PREFIX = "swarm/"
#: How long a clone may take before it is given up on.
CLONE_TIMEOUT_S = 300.0
#: How long any other git call may take.
GIT_TIMEOUT_S = 60.0

#: What a repository to clone may look like: a URL git fetches over the
#: network, or an absolute path the hub can read. Anything else is refused,
#: which also keeps git's command-running transports (``ext::``) out.
_REMOTE = re.compile(r"^(?:https?|ssh|git)://\S+$|^[\w.-]+@[\w.-]+:\S+$")
_UNSAFE = re.compile(r"[^A-Za-z0-9._-]+")

#: One lock per room: git refuses two worktree changes to one repository at once.
_locks: dict[str, threading.Lock] = {}
_locks_guard = threading.Lock()


class WorkspaceError(RuntimeError):
    """The workspace could not be set up; the message says why, for a person."""


@dataclass(frozen=True)
class Checkout:
    """One member's checkout: where it is, its branch, and what it came from."""

    path: Path
    branch: str
    base: str
    origin: str | None

    def describe(self) -> str:
        """The checkout, as a worker is told about it at the start of a turn."""
        source = f"a clone of {self.origin}" if self.origin else "a new, empty repository"
        return (
            f"Your checkout is {self.path} ({source}), on your own branch {self.branch}, "
            f"started from {self.base}. Each teammate works on its own branch, "
            f"{BRANCH_PREFIX}<handle>, in the same repository, so you can read theirs "
            f"(git log, git diff {self.base}...{BRANCH_PREFIX}<handle>) and merge them."
        )


def _root(room: str) -> Path:
    from app.services.filesystem import get_data_dir

    return get_data_dir() / WORKSPACES / _UNSAFE.sub("-", room).strip("-")


def _lock(room: str) -> threading.Lock:
    with _locks_guard:
        return _locks.setdefault(room, threading.Lock())


def _git(
    *args: str, cwd: Path | None = None, timeout: float = GIT_TIMEOUT_S
) -> subprocess.CompletedProcess[str]:
    env = {**os.environ, "GIT_TERMINAL_PROMPT": "0"}
    try:
        done = subprocess.run(
            ["git", *args],
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
            stdin=subprocess.DEVNULL,
            env=env,
        )
    except FileNotFoundError as exc:
        raise WorkspaceError("git is not installed on the hub") from exc
    except subprocess.TimeoutExpired as exc:
        raise WorkspaceError(f"git {args[0]} took longer than {timeout:.0f}s") from exc
    if done.returncode != 0:
        detail = (done.stderr or done.stdout).strip().splitlines()
        raise WorkspaceError(f"git {args[0]} failed: {detail[-1] if detail else done.returncode}")
    return done


def valid_repo(repo: str) -> bool:
    """Whether ``repo`` is something the hub may clone."""
    repo = repo.strip()
    if not repo or repo.startswith("-"):
        return False
    return bool(_REMOTE.match(repo)) or Path(repo).is_absolute()


def origin_of(room: str) -> str | None:
    """The repository a room's workspace was cloned from, or ``None``."""
    repo = _root(room) / REPO
    if not (repo / ".git").exists():
        return None
    try:
        return _git("remote", "get-url", "origin", cwd=repo).stdout.strip() or None
    except WorkspaceError:
        return None


def prepare(room: str, repo: str | None = None) -> Path:
    """Make sure ``room`` has its shared repository, and return its path.

    With ``repo``, it is cloned the first time; a room already working on the
    same repository fetches it instead, and one working on a different one is
    refused rather than silently switched. Without ``repo``, a room that has
    none gets an empty repository with one commit to branch from.
    """
    wanted = repo.strip() if repo else None
    if wanted is not None and not valid_repo(wanted):
        raise WorkspaceError(
            f"{wanted!r} is not a repository the hub can clone: use an https, ssh "
            "or git@ URL, or an absolute path on the hub"
        )
    root = _root(room)
    shared = root / REPO
    with _lock(room):
        if (shared / ".git").exists():
            if wanted is not None:
                have = origin_of(room)
                if have != wanted:
                    raise WorkspaceError(
                        f"this room already works on {have or 'its own repository'}; "
                        "start the swarm in another room to use a different one"
                    )
                try:
                    _git("fetch", "--quiet", "origin", cwd=shared, timeout=CLONE_TIMEOUT_S)
                except WorkspaceError as exc:
                    logger.warning("room %s: could not fetch %s: %s", room, wanted, exc)
            return shared
        root.mkdir(parents=True, exist_ok=True)
        if wanted is not None:
            _git("clone", "--quiet", "--", wanted, str(shared), timeout=CLONE_TIMEOUT_S)
        else:
            _git("init", "--quiet", "-b", "main", str(shared))
            _git(
                "-c",
                "user.name=mycelium",
                "-c",
                "user.email=mycelium@localhost",
                "commit",
                "--quiet",
                "--allow-empty",
                "-m",
                "Start the team's repository",
                cwd=shared,
            )
        logger.info("room %s: workspace ready at %s", room, shared)
        return shared


def checkout_for(room: str, handle: str) -> Checkout:
    """``handle``'s own checkout in ``room``, made the first time it is asked for."""
    shared = prepare(room)
    name = _UNSAFE.sub("-", handle).strip("-") or "member"
    path = _root(room) / name
    branch = f"{BRANCH_PREFIX}{name}"
    with _lock(room):
        base = _git("rev-parse", "--abbrev-ref", "HEAD", cwd=shared).stdout.strip() or "main"
        if not path.exists():
            _git("worktree", "add", "--quiet", "-B", branch, str(path), base, cwd=shared)
    return Checkout(path=path, branch=branch, base=base, origin=origin_of(room))


def identity(handle: str) -> dict[str, str]:
    """The git author a member's commits carry: the member, not the hub."""
    email = f"{_UNSAFE.sub('-', handle).strip('-') or 'member'}@mycelium.local"
    return {
        "GIT_AUTHOR_NAME": handle,
        "GIT_AUTHOR_EMAIL": email,
        "GIT_COMMITTER_NAME": handle,
        "GIT_COMMITTER_EMAIL": email,
        "GIT_TERMINAL_PROMPT": "0",
    }
