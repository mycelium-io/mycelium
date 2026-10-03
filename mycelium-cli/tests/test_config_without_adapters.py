# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""A config written before ``mycelium adapter`` was removed still loads.

``adapter add`` recorded each install under an ``[adapters]`` table in
``config.toml``. Nothing reads it now, and a machine that ran it keeps the
table, so the loader has to pass over it rather than refuse the file.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from mycelium.config import MyceliumConfig

if TYPE_CHECKING:
    from pathlib import Path


def test_an_old_adapters_table_is_ignored(isolated_home: Path) -> None:
    path = MyceliumConfig.get_config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "[server]\n"
        'api_url = "http://hub.test:8000"\n'
        "\n"
        "[adapters.claude-code]\n"
        'type = "claude-code"\n'
        'installed_at = "2026-08-11T10:00:00"\n'
        'api_url = "http://localhost:8000"\n',
        encoding="utf-8",
    )

    config = MyceliumConfig.load()

    assert config.server.api_url == "http://hub.test:8000"
    assert not hasattr(config, "adapters")
