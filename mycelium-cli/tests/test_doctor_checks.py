# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""Unit tests for ``mycelium doctor`` checks beyond the mediator-Pi one.

Node-free: the checks are stubbed at their filesystem / subprocess seams, so the
local-backend classifier and the config-files check run without a live stack.
The mediator-Pi check has its own file (``test_doctor_mediator_pi``).
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from mycelium.commands import doctor
from mycelium.config import MyceliumConfig
from mycelium.slim import naming


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("http://localhost:8000", True),
        ("http://127.0.0.1:8000", True),
        ("http://0.0.0.0:8000", True),
        ("http://host-a.lan:8000", False),
        ("https://mycelium.example.com", False),
    ],
)
def test_is_local_backend_classifies_host(url: str, expected: bool) -> None:
    assert doctor._is_local_backend(url) is expected


def test_check_config_files_ok_when_present(isolated_home, monkeypatch: pytest.MonkeyPatch) -> None:
    myc = isolated_home / ".mycelium"
    myc.mkdir(parents=True, exist_ok=True)
    (myc / ".env").write_text("X=1")
    (myc / "config.toml").write_text("")

    result = doctor._check_config_files()
    assert result.status == "ok"


def test_check_config_files_errors_when_missing(
    isolated_home, monkeypatch: pytest.MonkeyPatch
) -> None:
    # isolated_home is an empty temp home → both files absent.
    result = doctor._check_config_files()
    assert result.status == "error"
    assert ".env" in result.message and "config.toml" in result.message
    assert any("mycelium install" in d for d in result.details)


def test_check_http_auth_gate_warns_on_remote_ungated(monkeypatch: pytest.MonkeyPatch) -> None:
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"auth": {"enabled": False}}
    monkeypatch.setattr("httpx.get", lambda *a, **k: mock_resp)

    result = doctor._check_http_auth_gate(api_url="http://hub.lan:8000")
    assert result.status == "warning"
    assert "JWT gate is off" in result.message


def test_check_http_auth_gate_ok_on_localhost_ungated(monkeypatch: pytest.MonkeyPatch) -> None:
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"auth": {"enabled": False}}
    monkeypatch.setattr("httpx.get", lambda *a, **k: mock_resp)

    result = doctor._check_http_auth_gate(api_url="http://localhost:8000")
    assert result.status == "ok"


def test_check_hub_slim_psk_skipped_on_spoke() -> None:
    assert doctor._check_hub_slim_psk(local_backend=False) is None


def test_check_hub_slim_psk_warns_on_dev_secret(isolated_home) -> None:
    myc = isolated_home / ".mycelium"
    myc.mkdir(parents=True, exist_ok=True)
    config = MyceliumConfig()
    config.slim.master_secret = naming._DEV_MASTER_SECRET
    config.save(myc / "config.toml")

    result = doctor._check_hub_slim_psk(local_backend=True)
    assert result is not None
    assert result.status == "warning"
    assert "public dev" in result.message


def test_check_hub_slim_psk_ok_with_private_secret(isolated_home) -> None:
    myc = isolated_home / ".mycelium"
    myc.mkdir(parents=True, exist_ok=True)
    config = MyceliumConfig()
    config.slim.master_secret = "my-private-hub-secret-0123456789abcd"
    config.save(myc / "config.toml")

    result = doctor._check_hub_slim_psk(local_backend=True)
    assert result is not None
    assert result.status == "ok"
