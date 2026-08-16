# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""`_compose_base_cmd` must enable the `spire` profile when slim.identity=spire.

SPIRE is the one-switch attested-identity tier (#588): the config drives the
compose profile, so `mycelium up` / `down` / `logs` all include the SPIRE
server+agent when — and only when — `MYCELIUM_SLIM_IDENTITY=spire` is set in the
user's .env. On the default `psk` the profile is absent and the stack is unchanged.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from mycelium.commands import instance


def _has_profile(cmd: list[str], name: str) -> bool:
    return any(cmd[i] == "--profile" and cmd[i + 1] == name for i in range(len(cmd) - 1))


def _cmd(tmp_path: Path, **kwargs) -> list[str]:
    return instance._compose_base_cmd(
        compose_path=tmp_path / "compose.yml",
        env_path=tmp_path / ".env",
        project_name="proj",
        **kwargs,
    )


def _write_env(tmp_path: Path, identity: str | None) -> None:
    lines = ["MYCELIUM_BACKEND_PORT=8000"]
    if identity is not None:
        lines.append(f"MYCELIUM_SLIM_IDENTITY={identity}")
    (tmp_path / ".env").write_text("\n".join(lines) + "\n")


@pytest.fixture(autouse=True)
def _quiet_other_profiles(monkeypatch: pytest.MonkeyPatch) -> None:
    # Isolate the spire assertion from cfn/metrics/ui auto-detection.
    monkeypatch.setattr(instance, "_cfn_enabled", lambda: False)
    monkeypatch.setattr(instance, "_collector_container_running", lambda: False)
    monkeypatch.setattr(instance, "_frontend_container_running", lambda: False)
    monkeypatch.setattr(instance, "_get_env_path", lambda: None)


def test_spire_profile_added_when_identity_spire(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write_env(tmp_path, "spire")
    monkeypatch.setattr(instance, "_get_env_path", lambda: tmp_path / ".env")
    assert _has_profile(_cmd(tmp_path), "spire")


@pytest.mark.parametrize("identity", ["psk", "signerjwt", None])
def test_spire_profile_omitted_off_the_spire_tier(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, identity: str | None
) -> None:
    _write_env(tmp_path, identity)
    monkeypatch.setattr(instance, "_get_env_path", lambda: tmp_path / ".env")
    assert not _has_profile(_cmd(tmp_path), "spire")


def test_spire_profile_opt_out(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _write_env(tmp_path, "spire")
    monkeypatch.setattr(instance, "_get_env_path", lambda: tmp_path / ".env")
    assert not _has_profile(_cmd(tmp_path, include_spire_profile=False), "spire")


def test_spire_enabled_false_without_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(instance, "_get_env_path", lambda: None)
    assert instance._spire_enabled() is False


def test_spire_enabled_reads_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _write_env(tmp_path, "spire")
    monkeypatch.setattr(instance, "_get_env_path", lambda: tmp_path / ".env")
    assert instance._spire_enabled() is True
