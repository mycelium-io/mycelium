# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""`_compose_base_cmd` must enable the `ui` profile when the frontend is running.

The frontend service is profile-gated (`profiles: [ui]`). Commands like
`mycelium logs` / `down` / `stop` build their docker-compose invocation via
`_compose_base_cmd`; if it doesn't pass `--profile ui`, compose treats the
frontend as out of scope and silently skips it — so its logs never show up and
`down` leaves it running. This mirrors the existing `metrics` auto-detection.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from mycelium.commands import instance


def _has_profile(cmd: list[str], name: str) -> bool:
    return any(cmd[i] == "--profile" and cmd[i + 1] == name for i in range(len(cmd) - 1))


def _patch_profiles(
    monkeypatch: pytest.MonkeyPatch, *, frontend: bool, collector: bool = False, cfn: bool = False
) -> None:
    monkeypatch.setattr(instance, "_cfn_enabled", lambda: cfn)
    monkeypatch.setattr(instance, "_collector_container_running", lambda: collector)
    monkeypatch.setattr(instance, "_frontend_container_running", lambda: frontend)


def _cmd(tmp_path: Path, **kwargs) -> list[str]:
    return instance._compose_base_cmd(
        compose_path=tmp_path / "compose.yml",
        env_path=tmp_path / ".env",
        project_name="proj",
        **kwargs,
    )


def test_ui_profile_added_when_frontend_running(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _patch_profiles(monkeypatch, frontend=True)
    assert _has_profile(_cmd(tmp_path), "ui")


def test_ui_profile_omitted_when_frontend_not_running(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _patch_profiles(monkeypatch, frontend=False)
    assert not _has_profile(_cmd(tmp_path), "ui")


def test_ui_profile_opt_out_even_when_running(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # `up` opts out so it stays flag-driven (--ui), not driven by running state.
    _patch_profiles(monkeypatch, frontend=True)
    assert not _has_profile(_cmd(tmp_path, include_ui_profile=False), "ui")
