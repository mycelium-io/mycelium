# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""An agent CLI as Mycelium knows it, and the manifest one of its agents gets.

:class:`AgentKind` is everything Mycelium knows about one agent CLI: how the
scan finds it, the kind herdr starts it as, what it is started with, and what
to tell a person when it stops at a prompt. A CLI with nothing of its own is
this class as it is; one with something subclasses it in a module beside this
one. :class:`ResidentIntegration` is the ``agents/<handle>`` manifest for a
resident agent, which every CLI shares unless its module says otherwise.
"""

from __future__ import annotations

import functools
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, ClassVar

from mycelium.integrations.base import AddOptions, Integration
from mycelium.protocol import AgentManifest

if TYPE_CHECKING:
    from mycelium.config import MyceliumConfig


@dataclass(frozen=True)
class AgentKind:
    """An agent CLI: what the scan looks for and what Mycelium adds when it starts one."""

    id: str
    name: str
    #: Executables that mean it is installed, first match wins.
    binaries: tuple[str, ...]
    #: The kind herdr starts it as, when herdr has one.
    herdr_kind: str | None

    #: The manifest family its agents are recorded under (``AgentManifest.adapter``).
    adapter: ClassVar[str] = "claude_code"

    def launch_args(self) -> list[str]:
        """Arguments every agent of this kind starts with."""
        return []

    def resume_args(self, session: str) -> list[str] | None:  # noqa: ARG002 - a CLI that can resume says how
        """Arguments that start it in ``session``, its conversation so far; ``None``
        when it can't be resumed that way, and a restart starts a new session."""
        return None

    def blocked_hint(self) -> str | None:
        """A line on what it commonly waits for when its host reads it as blocked."""
        return None

    def interrupt_key(self) -> str:
        """The key that stops its current turn and keeps its session, as herdr names
        keys. Escape for the agent TUIs this table knows."""
        return "esc"

    def offers(self, *words: str) -> bool:
        """Whether the installed CLI's own ``--help`` mentions every one of ``words``.

        A flag a CLI added in a recent release is passed only to an install that
        has it: an older one would refuse to start over an option it doesn't
        know, which is worse than starting without it.
        """
        found = next((p for b in self.binaries if (p := shutil.which(b))), None)
        if not found:
            return False
        try:
            stamp = Path(found).stat().st_mtime
        except OSError:
            return False
        text = _help_text(found, stamp)
        return all(w in text for w in words)


@functools.cache
def _help_text(binary: str, stamp: float) -> str:  # noqa: ARG001 - a new install is a new key
    """What ``binary --help`` prints, read once per installed binary."""
    try:
        done = subprocess.run(  # noqa: S603 - the CLI's own path, from the scan's table
            [binary, "--help"], capture_output=True, text=True, timeout=15, check=False
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    return f"{done.stdout}\n{done.stderr}"


class ResidentIntegration(Integration):
    """The manifest of an agent a person or the runner runs: the manifest IS the registration.

    A resident agent is a session that takes part through ``await``/``respond``;
    Mycelium names it and does not run the process, so registering and
    destroying one has no side effects. ``claude_code`` is the family every
    agent CLI is recorded under unless its kind names another, a spelling kept
    because it is persisted in every manifest.
    """

    name = "claude_code"
    lifecycle = "resident"

    def __init__(self, *, cwd: str | None = None) -> None:
        self._cwd = cwd

    def build_manifest(
        self,
        *,
        handle: str,
        opts: AddOptions,
        description: str,
        allow_from: list[str],
        owner: str | None = None,
        team: str | None = None,
    ) -> AgentManifest:
        return AgentManifest(
            handle=handle,
            adapter=self.name,  # ty: ignore[invalid-argument-type]
            cwd=self._cwd,
            description=description,
            allow_from=allow_from,
            owner=owner,
            team=team,
        )

    def register(
        self, *, manifest: AgentManifest, config: MyceliumConfig, opts: AddOptions
    ) -> None:
        return

    def destroy(
        self, *, manifest: AgentManifest, config: MyceliumConfig, room: str, full: bool
    ) -> None:
        return

    def describe(self, manifest: AgentManifest, *, room: str) -> list[str]:
        lines: list[str] = [f"  adapter: {manifest.adapter}"]
        if manifest.cwd:
            lines.append(f"  cwd:     {manifest.cwd}")
        if manifest.allow_from:
            lines.append(f"  allow:   {', '.join(manifest.allow_from)}")
        lines.append(
            "\n[dim]Seed the agent's brain (optional):[/dim]\n"
            f'  mycelium memory set {manifest.notes_key} "..." --room {room}\n'
            "[dim]Keep the agent woken so it can answer:[/dim]\n"
            f'  mycelium await --loop --room {room} --handle {manifest.handle} --exec "..."\n'
            "[dim]Or address it (it picks up on its next await):[/dim]\n"
            f'  mycelium agent invoke {manifest.handle} "..."'
        )
        return lines
