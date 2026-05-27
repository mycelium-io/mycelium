# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Julia Valenti

"""Shared spawn types for cold-spawn integrations.

The daemon's dispatch loop calls ``Integration.spawn(request=SpawnRequest(...))``
on every ``@handle`` mention and consumes the returned ``SpawnResult``. Both
shapes are family-agnostic: claude_code and cursor (and future Gemini/Codex/
Aider) all produce/consume the same dataclass, so the daemon never branches
on family inside its core loop.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from mycelium.daemon.state import DaemonState


@dataclass(frozen=True)
class SpawnRequest:
    """Everything a cold-spawn integration needs to invoke one mention.

    All fields are required (no defaults) except the optional state handle
    used for ``RunningProc`` registration in the daemon core. Keeping this
    immutable means the daemon can pass it across the family boundary
    without worrying about in-place mutation.
    """

    handle: str
    """Agent handle this invocation runs as (without the leading ``@``)."""

    room: str
    """Room the mention came from."""

    cwd: str
    """Working directory the family's CLI runs in (already expanded)."""

    prompt: str
    """The user prompt with the leading ``@handle`` stripped."""

    description: str = ""
    """One-paragraph statement of what this agent does (from the manifest)."""

    sender: str = ""
    """Handle of the participant who issued the mention."""

    notes: str = ""
    """The agent's persistent notes (loaded from ``agents/<handle>/notes``)."""

    plan_block: str = ""
    """Optional plan-mode block injected into the preamble."""

    binary: str = ""
    """Path/name of the family's CLI binary (e.g. ``claude``, ``cursor-agent``).

    Empty means the family looks it up itself (e.g. from ``DaemonConfig``).
    """

    state: DaemonState | None = None
    """Daemon state for ``RunningProc`` registration. The daemon core now
    registers/clears this around the ``spawn`` call uniformly; family
    spawn implementations no longer touch ``state.running`` directly."""


@dataclass
class SpawnResult:
    """What a cold-spawn integration returns to the daemon.

    Mutable on purpose — some families enrich the result post-hoc (e.g.
    populating ``transcript_path`` after writing the invocation log). The
    daemon treats this as a structural record, not a wire type.
    """

    ok: bool
    """True if the spawn returned a usable reply; False on error/abort."""

    final_message: str
    """The agent's final reply text (posted back to the room)."""

    transcript: str
    """Raw stdout/stderr concatenation for the invocation log."""

    cost_usd: float = 0.0
    """USD spent on this invocation. ``0.0`` for families that don't expose
    per-call cost yet (e.g. cursor)."""

    duration_s: float = 0.0
    """Wall-clock time the spawn took."""

    aborted: bool = False
    """True if the process was terminated by an ``@handle abort`` SIGTERM."""

    extra: dict = field(default_factory=dict)
    """Family-specific fields (e.g. claude's ``rate_limit_event``). Opaque
    to the daemon; surfaced in invocation logs verbatim."""
