# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""Cursor Agent, and the manifest of one of its agents.

Its agents are recorded under their own family, ``cursor``. Registering one
writes nothing: a Cursor agent learns how to take part from
``mycelium skill print``, like every other agent. Destroying one with ``full``
clears the Cursor rule and AGENTS.md section older versions wrote into its
folder (:mod:`.workspace`).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, ClassVar

from mycelium.integrations.agents.base import AgentKind, ResidentIntegration
from mycelium.integrations.agents.cursor.workspace import uninstall_workspace_assets

if TYPE_CHECKING:
    from mycelium.config import MyceliumConfig
    from mycelium.protocol import AgentManifest


@dataclass(frozen=True)
class Cursor(AgentKind):
    adapter: ClassVar[str] = "cursor"


class CursorIntegration(ResidentIntegration):
    name = "cursor"

    def destroy(
        self, *, manifest: AgentManifest, config: MyceliumConfig, room: str, full: bool
    ) -> None:
        # Only ``full`` clears what an older register dropped, so the person's
        # project rules stay put otherwise.
        if full and manifest.cwd:
            cwd_path = Path(manifest.cwd)
            if cwd_path.exists():
                uninstall_workspace_assets(cwd_path, verbose=False)

    def will_destroy_runtime(self, manifest: AgentManifest, *, full: bool) -> bool:
        # ``full`` edits the person's working tree (AGENTS.md may be committed),
        # so the command layer asks first.
        return bool(full and manifest.cwd)
