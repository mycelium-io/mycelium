# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""Regression tests for ``mycelium doctor`` CFN checks on spoke nodes."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from mycelium.commands import doctor


def test_cfn_intent_skips_on_spoke() -> None:
    result = doctor._check_cfn_intent(local_backend=False)

    assert result.status == "ok"
    assert result.name == "CFN config"
    assert "spoke" in result.message.lower()


def test_cfn_intent_warns_on_hub_when_mas_id_without_cfn_urls(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    mycelium_dir = tmp_path / ".mycelium"
    mycelium_dir.mkdir()
    (mycelium_dir / ".env").write_text("WORKSPACE_ID=ws\n")
    (mycelium_dir / "config.toml").write_text(
        '[server]\nmas_id = "46c41ee3-7eb1-471b-8e24-0cdca6e7cbc4"\n'
    )

    monkeypatch.setattr(Path, "home", lambda: tmp_path)

    result = doctor._check_cfn_intent(local_backend=True)

    assert result.status == "warning"
    assert "mas_id" in result.message


def test_room_mas_ids_queries_hub_on_spoke_without_local_cfn_urls(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Spokes should verify hub rooms even when local CFN_MGMT_URL is empty."""
    mycelium_dir = tmp_path / ".mycelium"
    mycelium_dir.mkdir()
    (mycelium_dir / ".env").write_text("WORKSPACE_ID=ws\n")
    (mycelium_dir / "config.toml").write_text('[server]\napi_url = "http://10.0.50.125:8000"\n')

    monkeypatch.setattr(Path, "home", lambda: tmp_path)

    mock_resp = MagicMock()
    mock_resp.json.return_value = [{"name": "mycelium_room", "mas_id": "abc-123"}]
    mock_resp.raise_for_status = MagicMock()

    with patch("httpx.Client") as mock_client:
        mock_client.return_value.__enter__.return_value.get.return_value = mock_resp
        result = doctor._check_room_mas_ids(local_backend=False)

    assert result.status == "ok"
    assert "MAS ID" in result.message
    assert "CFN not enabled" not in result.message


def test_room_mas_ids_skips_on_hub_when_cfn_not_enabled(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    mycelium_dir = tmp_path / ".mycelium"
    mycelium_dir.mkdir()
    (mycelium_dir / ".env").write_text("WORKSPACE_ID=ws\n")

    monkeypatch.setattr(Path, "home", lambda: tmp_path)

    result = doctor._check_room_mas_ids(local_backend=True)

    assert result.status == "ok"
    assert result.message == "Skipped (CFN not enabled)"
