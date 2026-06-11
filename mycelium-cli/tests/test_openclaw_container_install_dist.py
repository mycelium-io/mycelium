# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""Container OpenClaw install builds the plugin and stages the compiled dist/.

Regression guard for #346 (item #2). When ``mycelium adapter add openclaw
--openclaw-container <c>`` runs, the container install path must:

1. Build the plugin (``npm install`` + ``npm run build``) before staging it,
   because OpenClaw >= 2026.5.3 rejects source-only plugins at install time —
   exactly as the host-native path has done since 0c5f524.
2. Stage the compiled ``dist/`` into the container's installed extension dir
   *after* ``openclaw plugins install`` (which blanket-excludes ``dist/``),
   mirroring the host path's post-install dist copy.

The April container path did neither: it ``docker cp``-d the raw TypeScript
source and ran ``openclaw plugins install`` with no build, so on a modern
OpenClaw the gateway aborts with ``extension entry not found: ./dist/index.js``.
This test pins the build-then-stage-dist ordering so the asymmetry can't
silently return.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from mycelium.integrations.openclaw import install as oc


class _Ok:
    """Stand-in for a successful ``subprocess.run`` result."""

    returncode = 0
    stdout = ""
    stderr = ""


def test_container_install_builds_then_stages_dist(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Fake plugin source tree carrying a dist/ (as produced by `npm run build`).
    plugin_src = tmp_path / "plugin"
    (plugin_src / "dist").mkdir(parents=True)
    (plugin_src / "dist" / "index.js").write_text("// built", encoding="utf-8")
    monkeypatch.setattr(oc, "_resolve_asset", lambda _name: plugin_src)

    # Neutralize the container-interaction helpers — we only care about the
    # build step and what gets staged.
    monkeypatch.setattr(oc, "_check_openclaw_version", lambda container=None: None)
    monkeypatch.setattr(oc, "_openclaw_container_home", lambda _container: "/root")
    monkeypatch.setattr(oc, "_wait_container_healthy", lambda _container, timeout=30: None)
    monkeypatch.setattr(oc, "_allow_plugin", lambda *a, **k: None)
    monkeypatch.setattr(oc, "_install_openclaw_skill", lambda *a, **k: None)

    events: list[tuple[str, str]] = []

    def _fake_stage(container: str, src: Path, dest: str) -> None:
        events.append(("stage", dest))

    monkeypatch.setattr(oc, "_stage_assets_in_container", _fake_stage)

    def _fake_run(cmd: list[str], *args: object, **kwargs: object) -> _Ok:
        if cmd and cmd[0] == "npm":
            events.append(("npm", " ".join(cmd)))
        return _Ok()

    monkeypatch.setattr(subprocess, "run", _fake_run)

    oc._install_openclaw(container="gw", profile=None)

    kinds = [k for k, _ in events]
    # The plugin was built (npm install + npm run build) before any staging.
    assert ("npm", "npm run build") in events, f"plugin was not built: {events}"
    first_npm = kinds.index("npm")

    # The compiled dist/ was staged into the container's installed extension dir.
    dist_stage = [
        i
        for i, (kind, dest) in enumerate(events)
        if kind == "stage" and dest.endswith(f"/extensions/{oc._OPENCLAW_PLUGIN_NAME}/dist")
    ]
    assert dist_stage, f"compiled dist/ was never staged into the container: {events}"

    # Build happens before the dist is staged (you can't stage what isn't built).
    assert first_npm < dist_stage[0], f"dist staged before build: {events}"
