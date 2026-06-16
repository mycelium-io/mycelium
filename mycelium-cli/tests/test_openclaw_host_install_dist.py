# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""Host-native OpenClaw reinstall ships dist/ without requiring npm.

OpenClaw >= 2026.5.3 validates ``plugins.entries.mycelium`` against
``~/.openclaw/extensions/mycelium/dist/index.js``. The compiled dist/ is
committed and ships in the wheel (#354), so reinstall must copy it into the
extension dir even when ``npm run build`` is unavailable.
"""

from __future__ import annotations

import shutil
import subprocess
from collections.abc import Callable, Iterable
from pathlib import Path
from typing import Any, cast

import pytest

from mycelium.integrations.openclaw import install as oc


class _Ok:
    returncode = 0
    stdout = ""
    stderr = ""


class _Fail:
    returncode = 1
    stdout = ""
    stderr = "npm not found"


def test_host_reinstall_succeeds_with_shipped_dist_when_npm_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Reinstall must not depend on npm when committed dist/ is present."""
    plugin_src = tmp_path / "plugin"
    (plugin_src / "dist").mkdir(parents=True)
    (plugin_src / "dist" / "index.js").write_text("// shipped", encoding="utf-8")
    (plugin_src / "index.ts").write_text("// src", encoding="utf-8")

    state_dir = tmp_path / "openclaw"
    ext_dir = state_dir / "extensions" / oc._OPENCLAW_PLUGIN_NAME
    monkeypatch.setattr(oc, "_resolve_asset", lambda _name: plugin_src)
    monkeypatch.setattr(oc, "_openclaw_state_dir", lambda _profile: state_dir)
    monkeypatch.setattr(oc, "_check_openclaw_version", lambda container=None: None)
    monkeypatch.setattr(oc, "_allow_plugin", lambda *a, **k: None)
    monkeypatch.setattr(oc, "_install_openclaw_skill", lambda *a, **k: None)

    events: list[str] = []

    def _fake_run(cmd: list[str], *args: object, **kwargs: object) -> _Ok | _Fail:
        if cmd and cmd[0] == "npm":
            events.append("build")
            return _Fail()
        if len(cmd) >= 2 and cmd[0] == "openclaw" and cmd[1] == "plugins":
            events.append("plugins_install")
            return _Ok()
        return _Ok()

    monkeypatch.setattr(subprocess, "run", _fake_run)

    original_copytree = shutil.copytree

    def _tracking_copytree(src: str, dst: str, *args: Any, **kwargs: Any) -> None:
        if Path(dst) == ext_dir:
            events.append("copytree")
            ignore_fn = kwargs.get("ignore")
            if ignore_fn is None and len(args) >= 2:
                ignore_fn = args[1]
            assert callable(ignore_fn)
            filtered = cast(Callable[[str, list[str]], Iterable[str]], ignore_fn)(
                src, ["dist", "node_modules", "index.ts"]
            )
            assert "dist" not in filtered, f"dist/ must not be excluded on reinstall: {filtered}"
        original_copytree(src, dst, *args, **kwargs)

    monkeypatch.setattr(shutil, "copytree", _tracking_copytree)

    oc._install_openclaw(reinstall=True, profile=None)

    assert "copytree" in events
    assert "plugins_install" in events
    assert events.index("copytree") < events.index("plugins_install")
    assert (ext_dir / "dist" / "index.js").is_file()
