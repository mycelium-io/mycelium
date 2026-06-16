# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""Host-native OpenClaw reinstall builds dist/ before staging the extension.

Regression guard for the host ``--reinstall`` path. OpenClaw >= 2026.5.3
validates ``plugins.entries.mycelium`` against
``~/.openclaw/extensions/mycelium/dist/index.js`` on every CLI invocation.
The old reinstall sequence copied TypeScript-only source (``dist/`` excluded),
then built in the package tree, then ran ``openclaw plugins install`` — which
failed with ``extension entry not found: dist/index.js`` because the live
extension dir was still unbuilt when validation ran.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from mycelium.integrations.openclaw import install as oc


class _Ok:
    returncode = 0
    stdout = ""
    stderr = ""


def test_host_reinstall_builds_before_copy_and_keeps_dist(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    plugin_src = tmp_path / "plugin"
    (plugin_src / "dist").mkdir(parents=True)
    (plugin_src / "dist" / "index.js").write_text("// built", encoding="utf-8")
    (plugin_src / "index.ts").write_text("// src", encoding="utf-8")

    state_dir = tmp_path / "openclaw"
    ext_dir = state_dir / "extensions" / oc._OPENCLAW_PLUGIN_NAME
    monkeypatch.setattr(oc, "_resolve_asset", lambda _name: plugin_src)
    monkeypatch.setattr(oc, "_openclaw_state_dir", lambda _profile: state_dir)
    monkeypatch.setattr(oc, "_check_openclaw_version", lambda container=None: None)
    monkeypatch.setattr(oc, "_allow_plugin", lambda *a, **k: None)
    monkeypatch.setattr(oc, "_install_openclaw_skill", lambda *a, **k: None)

    events: list[str] = []

    def _fake_run(cmd: list[str], *args: object, **kwargs: object) -> _Ok:
        if cmd and cmd[0] == "npm":
            events.append("build")
        elif len(cmd) >= 2 and cmd[0] == "openclaw" and cmd[1] == "plugins":
            events.append("plugins_install")
        return _Ok()

    monkeypatch.setattr(subprocess, "run", _fake_run)

    original_copytree = shutil.copytree

    def _tracking_copytree(src: str, dst: str, *args: object, **kwargs: object) -> None:
        if Path(dst) == ext_dir:
            events.append("copytree")
            ignore = kwargs.get("ignore")
            assert ignore is not None
            filtered = ignore(src, ["dist", "node_modules", "index.ts"])
            assert "dist" not in filtered, f"dist/ must not be excluded on reinstall: {filtered}"
        original_copytree(src, dst, *args, **kwargs)

    monkeypatch.setattr(shutil, "copytree", _tracking_copytree)

    oc._install_openclaw(reinstall=True, profile=None)

    first_build = events.index("build")
    assert first_build < events.index("copytree"), events
    assert events.index("copytree") < events.index("plugins_install"), events
    assert (ext_dir / "dist" / "index.js").is_file()
