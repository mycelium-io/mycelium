# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""Single source of truth for the backend's release version string.

All places that need to embed the current release version (telemetry
resource attributes, analytics event payloads, health endpoint) should
call :func:`read_release` rather than each parsing ``pyproject.toml``
independently.
"""

from __future__ import annotations

import functools
import logging
from pathlib import Path

_log = logging.getLogger(__name__)


@functools.lru_cache(maxsize=1)
def read_release() -> str:
    """Return the ``project.version`` from ``pyproject.toml``, or ``'unknown'``.

    Result is cached after the first call so repeated access (e.g. one per
    aligner round) is O(1) after warmup.
    """
    try:
        import tomllib

        _p = Path(__file__).resolve().parent.parent.parent / "pyproject.toml"
        return tomllib.loads(_p.read_text())["project"]["version"]
    except Exception:
        return "unknown"
