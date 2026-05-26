# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Julia Valenti

"""``mycelium upgrade`` must refresh ``~/.mycelium/docker/compose.yml``.

The bug it fixes: previously the CLI binary was replaced but the on-disk
compose template was never touched, so users running ``mycelium up`` after
upgrade silently kept executing an old compose against a new CLI. The fix
ships a hidden ``_refresh-templates`` subcommand that overwrites the on-disk
template with the bundled one, with a ``compose.yml.prev`` backup.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from mycelium.commands.install import _refresh_compose_templates


@pytest.fixture
def home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("HOME", str(tmp_path))
    return tmp_path


def test_refresh_writes_bundled_compose(home: Path) -> None:
    refreshed = _refresh_compose_templates()

    compose = home / ".mycelium" / "docker" / "compose.yml"
    assert compose in refreshed
    assert compose.exists()
    body = compose.read_text(encoding="utf-8")
    # Sanity: the bundled template defines the backend service.
    assert "mycelium-backend" in body


def test_refresh_overwrites_stale_template_and_backs_up(home: Path) -> None:
    compose = home / ".mycelium" / "docker" / "compose.yml"
    compose.parent.mkdir(parents=True)
    compose.write_text("STALE TEMPLATE", encoding="utf-8")

    _refresh_compose_templates()

    # Fresh body replaced the stale one.
    assert "STALE TEMPLATE" not in compose.read_text(encoding="utf-8")
    # And the stale body is preserved one slot back.
    backup = home / ".mycelium" / "docker" / "compose.yml.prev"
    assert backup.exists()
    assert backup.read_text(encoding="utf-8") == "STALE TEMPLATE"


def test_refresh_no_backup_when_disabled(home: Path) -> None:
    compose = home / ".mycelium" / "docker" / "compose.yml"
    compose.parent.mkdir(parents=True)
    compose.write_text("STALE", encoding="utf-8")

    _refresh_compose_templates(backup=False)

    assert "STALE" not in compose.read_text(encoding="utf-8")
    assert not (home / ".mycelium" / "docker" / "compose.yml.prev").exists()


def test_refresh_copies_initdb_scripts(home: Path) -> None:
    _refresh_compose_templates()

    initdb = home / ".mycelium" / "docker" / "initdb"
    assert initdb.is_dir()
    scripts = list(initdb.glob("*.sh"))
    assert scripts, "expected at least one initdb script to be copied"
    # CFN bootstrap script must land — Postgres needs it on first volume init.
    assert any(s.name == "create-cfn-cp-db.sh" for s in scripts)
