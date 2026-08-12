# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""Bundled-asset resolution shared by every integration's install facet.

The static assets (shell hooks, SKILL.md, workspace rules) live under
``mycelium.integrations.<family>.assets`` — colocated with the family that
owns it. This resolves a real filesystem path to them whether the package
is editable or zipped.
"""

from __future__ import annotations

import importlib.resources
import tempfile
from pathlib import Path


def _resolve_asset(subpath: str, family: str) -> Path:
    """
    Return a real filesystem path to a bundled asset for *family*.

    Assets are colocated with the family that owns them
    (``mycelium.integrations.<family>.assets``). *family* is the canonical
    underscore id (``claude_code``/``cursor``). For non-editable installs
    where the package lives inside a zip, extract the tree to a temp dir.
    """
    pkg = importlib.resources.files(f"mycelium.integrations.{family}.assets")
    parts = subpath.split("/")
    src = Path(str(pkg))
    for part in parts:
        src = src / part

    if src.exists():
        return src

    # Non-editable install: extract to a temp dir
    tmp = Path(tempfile.mkdtemp(prefix="mycelium-asset-"))
    dst = tmp / parts[-1]
    dst.mkdir(parents=True, exist_ok=True)
    ref = pkg
    for part in parts:
        ref = ref / part
    for entry in ref.iterdir():
        (dst / entry.name).write_bytes(entry.read_bytes())
    return dst
