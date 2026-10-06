# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""Cursor Agent, and the manifest of one of its agents.

Its agents are recorded under their own family, ``cursor``: registering one
drops the workspace-local Cursor rule and an AGENTS.md section into its folder
(:mod:`.workspace`) so the session knows how to coordinate.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, ClassVar

from mycelium.integrations.agents.base import AgentKind, ResidentIntegration
from mycelium.integrations.agents.cursor.workspace import (
    install_workspace_assets,
    uninstall_workspace_assets,
)

if TYPE_CHECKING:
    from mycelium.config import MyceliumConfig
    from mycelium.integrations.base import AddOptions
    from mycelium.protocol import AgentManifest


@dataclass(frozen=True)
class Cursor(AgentKind):
    adapter: ClassVar[str] = "cursor"


class CursorIntegration(ResidentIntegration):
    name = "cursor"

    def register(
        self, *, manifest: AgentManifest, config: MyceliumConfig, opts: AddOptions
    ) -> None:
        # Raises NotADirectoryError when the folder doesn't exist; the command
        # layer reports it as a validation error.
        if manifest.cwd:
            install_workspace_assets(Path(manifest.cwd), verbose=False)

    def destroy(
        self, *, manifest: AgentManifest, config: MyceliumConfig, room: str, full: bool
    ) -> None:
        # Only ``full`` removes what register dropped, so a re-add picks up
        # where it left off and the person's project rules stay put.
        if full and manifest.cwd:
            cwd_path = Path(manifest.cwd)
            if cwd_path.exists():
                uninstall_workspace_assets(cwd_path, verbose=False)

    def will_destroy_runtime(self, manifest: AgentManifest, *, full: bool) -> bool:
        # ``full`` edits the person's working tree (AGENTS.md may be committed),
        # so the command layer asks first.
        return bool(full and manifest.cwd)
