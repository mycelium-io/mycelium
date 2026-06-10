# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""``mycelium agent add`` bails with chown guidance when ~/.mycelium is
root-owned, instead of raising a raw ``PermissionError`` halfway through.

Cloud-install symptom (#13 from #326): something earlier in the install runs
as root and root-owns part of ``~/.mycelium/`` (sudo step, gateway in a
container with a bind mount, etc.). Later ``mycelium agent add`` fails with
no signal about how to recover. The pre-check + the PermissionError catch
both surface the same one-line fix: ``sudo chown -R $USER ~/.mycelium``.
"""

from __future__ import annotations

import os
import platform
from pathlib import Path

import pytest
import typer

from mycelium.commands.agent import _check_writable_or_bail

pytestmark = pytest.mark.skipif(
    platform.system() == "Windows",
    reason="uid ownership has no equivalent on Windows",
)


def test_passes_when_target_dir_is_ours(tmp_path: Path) -> None:
    target = tmp_path / "rooms" / "demo" / "agents" / "alice.md"
    # No file yet; closest existing ancestor is tmp_path, which we own.
    _check_writable_or_bail(target)  # must not raise


def test_passes_when_existing_file_is_ours(tmp_path: Path) -> None:
    target = tmp_path / "alice.md"
    target.write_text("hello", encoding="utf-8")
    _check_writable_or_bail(target)  # must not raise


def test_bails_when_ancestor_owned_by_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    target = tmp_path / "rooms" / "demo" / "agents" / "alice.md"
    target.parent.mkdir(parents=True)

    # Closest existing ancestor "is owned by uid 0 (root)" while we're
    # some other uid. The helper should bail with typer.Exit(1).
    monkeypatch.setattr("mycelium.commands.agent._owner_uid", lambda p: 0)
    monkeypatch.setattr(os, "getuid", lambda: 1000)

    with pytest.raises(typer.Exit) as exc_info:
        _check_writable_or_bail(target)
    assert exc_info.value.exit_code == 1


def test_silent_when_stat_fails(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    target = tmp_path / "alice.md"

    # _owner_uid returns None when stat fails — fall through, let the real
    # write surface its own error rather than confusing the user.
    monkeypatch.setattr("mycelium.commands.agent._owner_uid", lambda p: None)
    monkeypatch.setattr(os, "getuid", lambda: 1000)

    _check_writable_or_bail(target)  # must not raise
