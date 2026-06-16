# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""Regression tests for ``mycelium doctor`` CFN intent check on spokes."""

from __future__ import annotations

from pathlib import Path

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
