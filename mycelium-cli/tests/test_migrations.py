# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""Tests for mycelium.migrations — host vs container alembic routing."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from mycelium.migrations import (
    AlembicRunResult,
    backend_container_running,
    find_local_backend_dir,
    run_alembic_upgrade,
)


def test_find_local_backend_dir_returns_none_without_checkout(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)

    class FakeFiles:
        def __str__(self) -> str:
            return str(tmp_path / "site-packages" / "mycelium")

    monkeypatch.setattr(
        "importlib.resources.files",
        lambda _pkg: FakeFiles(),
    )

    assert find_local_backend_dir() is None


def test_find_local_backend_dir_finds_fastapi_backend_under_cwd(monkeypatch, tmp_path):
    backend = tmp_path / "fastapi-backend"
    backend.mkdir()
    (backend / "alembic.ini").write_text("[alembic]\n")
    monkeypatch.chdir(tmp_path)

    class FakeFiles:
        def __str__(self) -> str:
            return str(tmp_path / "site-packages" / "mycelium")

        @property
        def parents(self):
            return []

    monkeypatch.setattr("importlib.resources.files", lambda _pkg: FakeFiles())

    assert find_local_backend_dir() == backend


def test_run_alembic_upgrade_uses_container_when_no_local_backend(monkeypatch):
    monkeypatch.setattr("mycelium.migrations.find_local_backend_dir", lambda: None)
    monkeypatch.setattr("mycelium.migrations.backend_container_running", lambda: True)

    expected = AlembicRunResult(0, "ok\n", "", "container")
    with patch(
        "mycelium.migrations._run_container_alembic", return_value=expected
    ) as run_container:
        result = run_alembic_upgrade("head")

    assert result == expected
    run_container.assert_called_once_with(["upgrade", "head"])


def test_run_alembic_upgrade_prefers_local_backend(monkeypatch, tmp_path):
    backend = tmp_path / "fastapi-backend"
    backend.mkdir()
    (backend / "alembic.ini").write_text("[alembic]\n")

    monkeypatch.setattr("mycelium.migrations.find_local_backend_dir", lambda: backend)
    expected = AlembicRunResult(0, "ok\n", "", "host")
    with patch("mycelium.migrations._run_host_alembic", return_value=expected) as run_host:
        result = run_alembic_upgrade("head")

    assert result == expected
    run_host.assert_called_once_with(backend, ["upgrade", "head"])


def test_run_alembic_upgrade_unavailable_when_no_backend_and_container_down(monkeypatch):
    monkeypatch.setattr("mycelium.migrations.find_local_backend_dir", lambda: None)
    monkeypatch.setattr("mycelium.migrations.backend_container_running", lambda: False)

    result = run_alembic_upgrade("head")

    assert result.mode == "unavailable"
    assert result.returncode == 1


def test_backend_container_running_true(monkeypatch):
    monkeypatch.setattr(
        "subprocess.run",
        lambda *args, **kwargs: MagicMock(returncode=0, stdout="true\n"),
    )
    assert backend_container_running() is True
