# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""herdr bridge — an *optional* persistent-runtime wake target for mycelium.

herdr (https://herdr.dev) keeps coding-agent sessions alive, addressable, and
wakeable across detach. mycelium coordinates agents via rooms + the SLIM channel
but has no persistent runtime of its own: a non-resident ``agent invoke`` message
queues on the durable cursor with nothing to wake it.

This package is the seam that closes that gap **without** coupling mycelium to
herdr. Everything here is best-effort and fail-soft: if the ``herdr`` CLI is
absent, its server is down, or no pane is mapped for a handle, callers fall back
to the pure-CLI ``await``/``respond`` path. herdr supplies *wake + liveness*;
mycelium supplies the *reply channel* (the room). The two never overlap — which
is why herdr's inability to scrape alt-screen TUI output never bites us.

- :mod:`bridge` — a thin, dependency-free wrapper over the ``herdr`` CLI plus a
  durable ``mycelium handle -> herdr pane`` registry.
"""

from __future__ import annotations

from mycelium.integrations.herdr.bridge import (
    HerdrBridge,
    HerdrError,
    HerdrPaneMapping,
    HerdrRegistry,
    HerdrUnavailableError,
    WakeResult,
    build_mention_prompt,
    build_wake_prompt,
)

__all__ = [
    "HerdrBridge",
    "HerdrError",
    "HerdrPaneMapping",
    "HerdrRegistry",
    "HerdrUnavailableError",
    "WakeResult",
    "build_mention_prompt",
    "build_wake_prompt",
]
