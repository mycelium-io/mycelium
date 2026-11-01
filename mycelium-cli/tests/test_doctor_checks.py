# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""Unit tests for ``mycelium doctor`` checks beyond the engine-Pi one.

Node-free: the checks are stubbed at their filesystem / subprocess seams, so the
local-backend classifier and the config-files check run without a live stack.
The engine-Pi check has its own file (``test_doctor_engine_pi``).
"""

from __future__ import annotations

import pytest

from mycelium.commands import doctor
from mycelium.config import MyceliumConfig
from mycelium.slim import naming
from tests.conftest import install_stand_in_hub


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


def test_no_engines_model_says_who_needs_one(isolated_home) -> None:
    """Unset is a choice, not a fault: it says that only the engines that think
    need a model, and that your own agents don't."""
    myc = isolated_home / ".mycelium"
    myc.mkdir(parents=True, exist_ok=True)
    (myc / ".env").write_text("LLM_MODEL=\n")

    result = doctor._check_llm_connectivity(set_up="Set it in Settings")
    # The app and the desktop find the check by this name.
    assert result.name == "LLM connectivity"
    assert (result.status, result.message) == ("ok", "Engines' model not set")
    assert result.details is not None
    assert "personas, workers, the synthesizer, the verifier and hello" in result.details[0]
    assert "Your own agents don't" in result.details[0]
    assert result.details[1] == "Set it in Settings"


def test_doctor_says_what_the_engines_say_in_the_room() -> None:
    """The hub's engines say the same thing (``contracts/engines-model.json``)."""
    import json
    from pathlib import Path

    contract = json.loads(
        (Path(__file__).resolve().parents[2] / "contracts" / "engines-model.json").read_text()
    )
    assert contract["set_one"] == doctor.SET_ONE
    assert contract["engines_that_think"] == doctor.ENGINES_THAT_THINK
    assert contract["set_one"] in contract["no_model_text"]


def test_check_config_files_errors_when_missing(
    isolated_home, monkeypatch: pytest.MonkeyPatch
) -> None:
    # isolated_home is an empty temp home → both files absent.
    monkeypatch.delenv("MYCELIUM_API_URL", raising=False)
    result = doctor._check_config_files()
    assert result.status == "error"
    assert ".env" in result.message and "config.toml" in result.message
    assert any("mycelium install" in d for d in result.details)


def test_check_config_files_ok_when_configured_from_env(
    isolated_home, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An env-configured client has no config files by design, not by mistake."""
    monkeypatch.setenv("MYCELIUM_API_URL", "https://mycelium.example.com")

    result = doctor._check_config_files()
    assert result.status == "ok"
    assert "environment" in result.message


def _ungated_hub(monkeypatch: pytest.MonkeyPatch) -> None:
    """A hub whose ``/health`` says its sign-in gate is off."""
    install_stand_in_hub(monkeypatch).answer = lambda _request: {
        "status": "ok",
        "service": "mycelium-backend",
        "version": "0.0.0-test",
        "auth": {"enabled": False, "issuers": [], "localhost_bypass": False, "audience": None},
    }


def test_check_http_auth_gate_warns_on_remote_ungated(monkeypatch: pytest.MonkeyPatch) -> None:
    _ungated_hub(monkeypatch)

    result = doctor._check_http_auth_gate(api_url="http://hub.lan:8000")
    assert result.status == "warning"
    assert "JWT gate is off" in result.message


def test_check_http_auth_gate_ok_on_localhost_ungated(monkeypatch: pytest.MonkeyPatch) -> None:
    _ungated_hub(monkeypatch)

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
