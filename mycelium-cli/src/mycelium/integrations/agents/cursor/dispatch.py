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
    # Its Agent chat stays ``working`` for the whole conversation, so a wake
    # goes in as a follow-up rather than waiting for an idle that doesn't come.
    wakes_while_working: ClassVar[bool] = True
    # It opens with no Agent chat in it, and a prompt typed there is lost.
    no_chat_yet: ClassVar[str | None] = (
        "no Cursor Agent chat is open in its pane yet. Open one there and send it a "
        "message: its introduction and anything it was tagged in are held until then"
    )

    def blocked_hint(self) -> str | None:
        return (
            "Cursor Agent has no chat open in this pane yet, or is asking before it runs a command."
        )


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

    def wake_help(self, manifest: AgentManifest, *, room: str) -> str:
        return (
            "[dim]Cursor hears a Channel @mention in the Agent chat open in its herdr pane,\n"
            "even while that chat is working. Until a chat is open there (send it one\n"
            "message), the agent stays blocked and its first wake is held:[/dim]\n"
            f"  mycelium room wakes --room {room}\n"
            "[dim]Address it from the command line:[/dim]\n"
            f'  mycelium agent invoke {manifest.handle} "..."'
        )

    def will_destroy_runtime(self, manifest: AgentManifest, *, full: bool) -> bool:
        # ``full`` edits the person's working tree (AGENTS.md may be committed),
        # so the command layer asks first.
        return bool(full and manifest.cwd)
