# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""OpenCode."""

from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar

from mycelium.integrations.agents.base import AgentKind


@dataclass(frozen=True)
class OpenCode(AgentKind):
    # herdr reads it as idle as soon as it runs, before its screen is drawn:
    # an introduction typed then is lost, or lands without its Enter.
    draws_late: ClassVar[bool] = True

    def launch_env(self) -> dict[str, str]:
        # OpenCode checks for a new release a few seconds after it starts and
        # opens an "Update Available: Skip / Confirm" dialog over its input,
        # while herdr still reads it as idle. A wake typed then lands in the
        # dialog, and its Enter can answer it, updating the person's OpenCode.
        # So in the panes Mycelium starts, and only there, it doesn't check:
        # it still updates however the person updates it.
        return {"OPENCODE_DISABLE_AUTOUPDATE": "1"}
