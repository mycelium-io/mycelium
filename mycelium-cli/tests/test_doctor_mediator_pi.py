# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""Doctor's mediator-Pi check: the aligner runs on Pi, so warn only when Pi is
actually unreachable — i.e. a host-run backend with no `pi` on PATH. A dockerized
backend is satisfied by the image (which ships Pi), so it must NOT warn.
"""

from __future__ import annotations

import pytest

from mycelium.commands.doctor import _check_mediator_pi_binary


def test_dockerized_backend_is_ok_without_host_pi(monkeypatch: pytest.MonkeyPatch) -> None:
    """Backend container up → Pi lives in the image; no host binary needed."""
    monkeypatch.setattr("mycelium.commands.doctor._backend_container_running", lambda: True)
    monkeypatch.setattr("shutil.which", lambda _b: None)  # no host pi at all
    result = _check_mediator_pi_binary()
    assert result.status == "ok"
    assert "image" in result.message


def test_host_backend_without_pi_warns(monkeypatch: pytest.MonkeyPatch) -> None:
    """No backend container + no `pi` on PATH → warn (an @aligner summon would
    fail on a host-run backend), with the npm install hint."""
    monkeypatch.setattr("mycelium.commands.doctor._backend_container_running", lambda: False)
    monkeypatch.setattr("shutil.which", lambda _b: None)
    monkeypatch.delenv("ALIGNER_PI_BINARY", raising=False)
    result = _check_mediator_pi_binary()
    assert result.status == "warning"
    assert any("npm install -g @mariozechner/pi-coding-agent" in d for d in result.details)


def test_host_backend_with_pi_is_ok(monkeypatch: pytest.MonkeyPatch) -> None:
    """No container but `pi` is on PATH → satisfied."""
    monkeypatch.setattr("mycelium.commands.doctor._backend_container_running", lambda: False)
    monkeypatch.setattr("shutil.which", lambda _b: "/usr/local/bin/pi")
    result = _check_mediator_pi_binary()
    assert result.status == "ok"
    assert "/usr/local/bin/pi" in result.message


def test_respects_aligner_pi_binary_override(monkeypatch: pytest.MonkeyPatch) -> None:
    """The check resolves ALIGNER_PI_BINARY, not just the literal `pi`."""
    seen: list[str] = []

    def fake_which(binary: str) -> str | None:
        seen.append(binary)
        return "/opt/custom-pi"

    monkeypatch.setattr("mycelium.commands.doctor._backend_container_running", lambda: False)
    monkeypatch.setattr("shutil.which", fake_which)
    monkeypatch.setenv("ALIGNER_PI_BINARY", "custom-pi")
    result = _check_mediator_pi_binary()
    assert result.status == "ok"
    assert "custom-pi" in seen
