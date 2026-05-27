# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Julia Valenti

"""Identity preamble injected into every cold-spawned agent invocation.

Shared by all cold-spawn integrations (currently ``claude_code`` and
``cursor``). Each family injects it slightly differently:

- ``claude -p`` accepts ``--append-system-prompt <text>``, so claude_code
  passes the preamble as a flag value.
- ``cursor-agent -p`` has no system-prompt flag (verified against
  ``cursor-agent --help``); cursor instead **prepends** the preamble to
  the positional prompt with a ``---`` separator.

Without this, a cold-started agent has no idea it's been routed to as
``@handle`` — it tries to explain it's "actually <model name>," asks if
the user meant to route somewhere else, etc. (Mirrors how OpenClaw injects
identity via ``MYCELIUM_AGENT_HANDLE`` + ``before_agent_start``; cold-start
agents have no env channel for that, so we bake it into the prompt.)
"""

from __future__ import annotations


def identity_preamble(
    *,
    handle: str,
    room: str,
    description: str,
    sender: str,
    notes: str,
    plan_block: str = "",
) -> str:
    """Build the system-prompt preamble for a cold-spawn agent invocation.

    Family-agnostic — any cold-spawn integration consumes the same text
    and decides how to inject it into its underlying CLI.
    """
    desc_block = f"\n## Your scope\n\n{description.strip()}\n" if description.strip() else ""
    notes_block = (
        f"\n## Your persistent notes\n\n{notes.strip()}\n"
        if notes.strip()
        else "\n## Your persistent notes\n\n(none yet — `mycelium memory get agents/"
        f"{handle}/notes` shows them when they exist)\n"
    )
    return f"""\
# You are @{handle} — a Mycelium-hosted agent

You are operating as the agent **@{handle}** inside the Mycelium room
**{room}**. Another participant ({sender}) just @-mentioned you with the
prompt below. Your reply will be posted to that room *as @{handle}*, so:

- Respond in first person as @{handle}.
- Do NOT explain that you're "actually <some model>," ask whether the user
  meant the chat box, or offer to route them elsewhere — you ARE the
  routing destination.
- Do NOT prefix your reply with `@{handle}:` or quote the original
  message back — just answer.
- Keep replies tight. The room is a chat surface; long monologues
  belong in `decisions/` or `work/` memory entries, not the chat.
- You're cold-started: every invocation is fresh. Anything that should
  persist between runs goes in your notes (`mycelium memory set
  agents/{handle}/notes "..."` from your cwd).
{desc_block}{notes_block}{plan_block}
## Control verbs

If the prompt is exactly one of `abort`, `cancel`, `stop`, or `status`,
the daemon handles it before you see it — you'll never receive those.
"""
