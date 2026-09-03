# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""Tests for the post-``mycelium up`` image-tag announcement.

Compose silently falls back to ``:latest`` when ``MYCELIUM_IMAGE_TAG`` is
absent. ``_announce_image_tag`` surfaces the effective tag (and warns when
unpinned) so a debugging session sees it immediately instead of digging
through ``.env``.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from mycelium.commands import instance


@pytest.fixture
def env_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point ``_get_env_path`` at a temp .env so we never touch the user's."""
    env = tmp_path / ".env"
    monkeypatch.setattr(instance, "_get_env_path", lambda: env if env.exists() else None)
    return env


def test_announce_warns_when_no_env_file(
    env_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """No .env at all → user hasn't run ``mycelium install`` yet, or wiped
    state.  Either way, compose will use ``:latest`` — say so.
    """
    instance._announce_image_tag()
    out = capsys.readouterr().out
    assert "latest" in out
    assert "unpinned" in out


def test_announce_warns_when_pin_missing_from_env(
    env_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """``MYCELIUM_IMAGE_TAG`` may be absent from a regenerated .env (e.g.
    after ``mycelium config apply``); compose must not silently fall back to
    ``:latest`` without warning.
    """
    env_path.write_text("MYCELIUM_DB_PASSWORD=password\n", encoding="utf-8")
    instance._announce_image_tag()
    out = capsys.readouterr().out
    assert "latest" in out
    assert "unpinned" in out
    assert "mycelium pull --version" in out, "must hint at the fix"


def test_announce_reports_pinned_tag(env_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    env_path.write_text(
        "MYCELIUM_DB_PASSWORD=password\nMYCELIUM_IMAGE_TAG=1.0.14rc3\n",
        encoding="utf-8",
    )
    instance._announce_image_tag()
    out = capsys.readouterr().out
    assert "1.0.14rc3" in out
    assert "pinned" in out
    assert "unpinned" not in out


def test_announce_treats_explicit_latest_as_unpinned(
    env_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """``mycelium pull --version=latest`` records ``MYCELIUM_IMAGE_TAG=latest``
    as an explicit unpin — the user gets the same UX as if the line were
    absent (warning + hint), since the effective behavior is identical.
    """
    env_path.write_text("MYCELIUM_IMAGE_TAG=latest\n", encoding="utf-8")
    instance._announce_image_tag()
    out = capsys.readouterr().out
    assert "unpinned" in out
