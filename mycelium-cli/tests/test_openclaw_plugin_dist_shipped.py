# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""The OpenClaw plugin ships a committed, compiled dist/.

OpenClaw 2026.5+ rejects source-only plugins (it requires dist/index.js). The
compiled output is committed and shipped in the wheel so `mycelium adapter add
openclaw` works on machines without a Node toolchain, and so a reinstall can't
leave the extension dir without its entry. These tests guard that invariant:

1. the compiled entry is present on disk (committed, not gitignored away);
2. the entry openclaw.plugin.json / package.json declare actually exists;
3. the reinstall copy filter keeps dist/ (dropping it would wipe the entry from
   the extension dir and fail openclaw's config validation).
"""

from __future__ import annotations

import json
from pathlib import Path

from mycelium.integrations.openclaw import install as oc


def _plugin_dir() -> Path:
    return Path(oc.__file__).parent / "assets" / "mycelium" / "plugin"


def test_compiled_dist_entry_is_committed() -> None:
    entry = _plugin_dir() / "dist" / "index.js"
    assert entry.is_file(), (
        f"compiled plugin entry missing: {entry} — run `npm run build` in the "
        "plugin dir and commit dist/ (it ships in the wheel)."
    )


def test_declared_extension_entries_exist_on_disk() -> None:
    pkg = json.loads((_plugin_dir() / "package.json").read_text())
    entries = pkg.get("openclaw", {}).get("extensions", [])
    assert entries, "package.json openclaw.extensions is empty"
    for rel in entries:
        target = _plugin_dir() / rel
        assert target.is_file(), f"declared extension entry not shipped: {rel} ({target})"


def test_copy_ignore_keeps_dist_drops_dev_files() -> None:
    names = ["index.ts", "src", "dist", "node_modules", "test", "package-lock.json"]
    ignored = oc._plugin_copy_ignore("/whatever", names)
    assert "dist" not in ignored, "dist/ must be copied into the extension dir, not ignored"
    assert {"node_modules", "test", "package-lock.json"} <= set(ignored)
