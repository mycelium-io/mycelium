# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""The frontend is part of the stack, not an opt-in compose profile.

`mycelium-frontend` used to sit behind `profiles: [ui]`, so every command had
to enable that profile or compose silently skipped the service — its logs
never showed up and `down` left it running. It now starts with the node and
the backend, which means the compose file declares no profile for it and
`_compose_base_cmd` never passes `--profile ui`.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from mycelium.commands import instance

_COMPOSE = Path(__file__).parent.parent / "src" / "mycelium" / "docker" / "compose.yml"


def _services() -> dict:
    return yaml.safe_load(_COMPOSE.read_text())["services"]


def test_frontend_has_no_compose_profile() -> None:
    assert "profiles" not in _services()["mycelium-frontend"]


def test_metrics_collector_stays_profile_gated() -> None:
    # The collector is still opt-in; only the frontend graduated to always-on.
    assert _services()["mycelium-collector"]["profiles"] == ["metrics"]


def test_compose_base_cmd_never_passes_ui_profile(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(instance, "_cfn_enabled", lambda: False)
    monkeypatch.setattr(instance, "_collector_container_running", lambda: False)
    cmd = instance._compose_base_cmd(
        compose_path=tmp_path / "compose.yml",
        env_path=tmp_path / ".env",
        project_name="proj",
    )
    assert "ui" not in cmd


def test_frontend_is_a_managed_container() -> None:
    # `down` and container cleanup must reach the frontend now that nothing
    # gates it behind a profile.
    assert "mycelium-frontend" in instance._MANAGED_CONTAINERS
