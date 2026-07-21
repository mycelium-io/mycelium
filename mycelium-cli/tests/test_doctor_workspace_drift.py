# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""Tests for the standalone ``mycelium doctor`` WORKSPACE_ID drift check.

The check is a pure disk-to-disk (.env vs config.toml) comparison — it must
run regardless of backend health, unlike the runtime-config-drift check it was
split out of.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from mycelium.commands import doctor


def _seed(tmp_path: Path, env_ws: str, toml_ws: str) -> None:
    mycelium_dir = tmp_path / ".mycelium"
    mycelium_dir.mkdir()
    (mycelium_dir / ".env").write_text(f"WORKSPACE_ID={env_ws}\n")
    (mycelium_dir / "config.toml").write_text(f'[server]\nworkspace_id = "{toml_ws}"\n')


def test_workspace_drift_warns_on_mismatch(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _seed(tmp_path, env_ws="old-ws", toml_ws="new-ws")
    monkeypatch.setattr(Path, "home", lambda: tmp_path)

    result = doctor._check_workspace_id_drift()

    assert result.status == "warning"
    assert result.name == "Workspace ID drift"
    # The fix must point at `config apply`, not `mycelium up` (which would not
    # regenerate .env from config.toml).
    assert any("config apply" in d for d in (result.details or []))


def test_workspace_drift_ok_when_aligned(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _seed(tmp_path, env_ws="same-ws", toml_ws="same-ws")
    monkeypatch.setattr(Path, "home", lambda: tmp_path)

    result = doctor._check_workspace_id_drift()

    assert result.status == "ok"


def test_workspace_drift_skips_without_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    (tmp_path / ".mycelium").mkdir()
    monkeypatch.setattr(Path, "home", lambda: tmp_path)

    result = doctor._check_workspace_id_drift()

    assert result.status == "ok"
    assert "no .env" in result.message.lower()
