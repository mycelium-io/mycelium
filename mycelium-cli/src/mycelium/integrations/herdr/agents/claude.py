# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""Claude Code, as herdr's ``claude`` kind."""

from __future__ import annotations

import re
import uuid
from datetime import UTC, datetime
from pathlib import Path

from mycelium.integrations.herdr.agents import AgentKind, FoundSession

#: Claude Code names its sessions with UUIDs.
_SESSION_ID = re.compile(r"[0-9A-Fa-f]{8}-(?:[0-9A-Fa-f]{4}-){3}[0-9A-Fa-f]{12}")


def _tilde(path: str) -> str:
    home = str(Path.home())
    return "~" + path[len(home) :] if path.startswith(home) else path


class Claude(AgentKind):
    def __init__(self) -> None:
        super().__init__("claude")

    @property
    def name(self) -> str:
        return "Claude Code"

    def launch_args(self) -> list[str]:
        # It asks before every shell command it hasn't been allowed, and a
        # member stopped at a prompt on its first `mycelium await` never takes
        # its turn. So the one command it needs is allowed for this session
        # only, never in the person's settings.
        return ["--allowedTools", "Bash(mycelium:*)"]

    @property
    def resumes(self) -> bool:
        return True

    def new_session(self) -> tuple[list[str], str]:
        session = str(uuid.uuid4())
        return ["--session-id", session], session

    def resume_args(self, session: str) -> list[str]:
        valid = self.valid_session(session)
        if valid is None:
            msg = f"{session!r} isn't a Claude Code session id"
            raise ValueError(msg)
        return ["--resume", valid]

    def valid_session(self, value: object) -> str | None:
        if isinstance(value, str) and _SESSION_ID.fullmatch(value):
            return value
        return None

    def find_session(self, folder: Path) -> FoundSession | None:
        # Claude Code keeps each folder's transcripts under ~/.claude/projects,
        # in a directory named after the folder's path with every character
        # other than a letter, digit or dash made a dash.
        resolved = folder.expanduser().resolve()
        slug = "".join(c if c.isalnum() or c == "-" else "-" for c in str(resolved))
        project = Path.home() / ".claude" / "projects" / slug
        if not project.is_dir():
            return None
        transcripts = [p for p in project.glob("*.jsonl") if self.valid_session(p.stem) is not None]
        if not transcripts:
            return None
        newest = max(transcripts, key=lambda p: p.stat().st_mtime)
        when = datetime.fromtimestamp(newest.stat().st_mtime, tz=UTC).isoformat()
        return FoundSession(id=newest.stem, path=_tilde(str(newest)), modified=when)
