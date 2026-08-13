# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""Unit tests for ``mycelium doctor`` checks beyond the mediator-Pi one.

Node-free: the checks are stubbed at their filesystem / subprocess seams, so the
local-backend classifier and the config-files check run without a live stack.
The mediator-Pi check has its own file (``test_doctor_mediator_pi``).
"""

from __future__ import annotations

import pytest

from mycelium.commands import doctor


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
