# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""A member's notes, drafted from the line a person typed about it.

The Add member dialog asks what an agent is for. A person usually types one
line ("reviews my PRs"); the agent reads its notes every time it starts, so
those notes do better saying what it owns, how it works the room's board and
threads, and when it hands off. This asks the hub's Pi for that fuller draft,
in the second person the agent will read, with the room's other members named
so it can say who to ask. The person sees the draft in the box and edits it
before anything is written: nothing here touches the room.
"""

from __future__ import annotations

import tempfile
import uuid
from pathlib import Path
from typing import Literal

from app.config import settings

#: How long one draft may take.
TIMEOUT_S = 60.0

#: The longest brief a draft is asked from; past this it is already notes.
MAX_BRIEF_CHARS = 4000

#: What kind of member the notes are for, which changes what they need to say.
NotesKind = Literal["agent", "persona", "worker"]

_KIND_FRAME: dict[str, list[str]] = {
    "agent": [
        "The member is a coding agent (an agent CLI) running in a folder on "
        "someone's machine. It joins the room with the `mycelium` CLI: it takes tasks off "
        "the room's board, works each one in that task's thread, asks a teammate to review "
        "by @-mentioning them, and resolves the task when it is done.",
    ],
    "worker": [
        "The member is a coding agent the hub runs in its own git checkout of the room's "
        "repository. It is woken when a task is filed for it or someone mentions it, works "
        "the task in its thread, asks a teammate to review by @-mentioning them, and "
        "resolves what it finishes.",
    ],
    "persona": [
        "The member is a character a model plays in the room's conversations: it answers "
        "when mentioned, in character, and remembers what was said. It does no coding and "
        "runs no commands. Describe who they are, what they care about, how they talk and "
        "what they push back on.",
    ],
}


def build_prompt(
    brief: str,
    *,
    kind: NotesKind = "agent",
    handle: str = "",
    room_title: str = "",
    teammates: list[str] | None = None,
) -> str:
    """What Pi is asked: the brief, the kind of member, and the room around it."""
    who = f"@{handle}" if handle else "this member"
    lines = [
        f"Write the standing instructions for {who}, a member of a team room in Mycelium, "
        "a workspace where people and AI agents coordinate on a shared board of tasks.",
        "",
        *_KIND_FRAME[kind],
        "",
    ]
    if room_title:
        lines += [f"The room is called: {room_title}", ""]
    others = [f"@{t}" for t in (teammates or []) if t and t != handle]
    if others:
        lines += [
            "Its teammates in the room (the only handles you may name): " + ", ".join(others),
            "",
        ]
    lines += [
        "What the person adding it said it is for:",
        brief.strip()[:MAX_BRIEF_CHARS],
        "",
        "Expand that into instructions the member reads every time it starts.",
        "- Write to the member as `you`. Keep everything the person asked for and do not "
        "change its intent; add only what makes it concrete and workable.",
        "- Say what it owns and what it leaves to others, how it does the work, what a "
        "good result looks like, and when to ask a teammate or a person.",
        "- Name a teammate only from the list above, and only where the job plainly fits "
        "them; never invent a handle."
        if others
        else "- Do not name any @handle.",
        "- 120 to 250 words. Short paragraphs or a few bullets. No heading, no preamble, "
        "no sign-off, no code fences. Return only the instructions.",
    ]
    return "\n".join(lines)


def clean(text: str) -> str:
    """The draft without a fence or a heading a model wraps it in."""
    lines = text.strip().splitlines()
    if lines and lines[0].startswith("```"):
        lines = lines[1:]
        if lines and lines[-1].startswith("```"):
            lines = lines[:-1]
    if lines and lines[0].lstrip().startswith("#"):
        lines = lines[1:]
    return "\n".join(lines).strip()


def complete(prompt: str, room: str) -> str:
    """One blocking Pi turn on a throwaway session. Isolated so tests patch it."""
    from app.services.pi_session import PiSession

    session_dir = Path(tempfile.gettempdir()) / "mycelium-pi-sessions"
    session_dir.mkdir(parents=True, exist_ok=True)
    session = PiSession(
        session_path=session_dir / f"notes-draft-{uuid.uuid4().hex}.jsonl",
        model=settings.LLM_MODEL,
        api_key=settings.LLM_API_KEY,
        base_url=settings.LLM_BASE_URL,
        binary=settings.ALIGNER_PI_BINARY,
        timeout_s=TIMEOUT_S,
        openshell=settings.ALIGNER_PI_OPENSHELL,
        operation="notes_draft",
        room=room,
    )
    return session(prompt)
