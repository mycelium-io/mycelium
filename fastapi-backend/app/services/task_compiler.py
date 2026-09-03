# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""Task compiler — turns a negotiation consensus into the room's work.

When structured negotiation reaches consensus, the aligner produces a flat
``issue=value`` agreement dict. That records *what was agreed* but is not
something anyone can pick up. This module is a separate stage that *consumes*
that consensus and compiles it — via one LLM call — into concrete tasks.

**A task is a row, not a line in a document.** Each one becomes a ``work/``
memory with its own frontmatter, so it can carry an owner, a status and a
lease, be grouped and filtered like anything else in the room, and be moved by
a board action. A shared checklist could do none of that: a ``- [ ]`` line has
nowhere to put a field.

The LLM still writes checklist lines, because that is the shape it is good at
and the prompt is proven. Parsing them into rows is this module's job, and the
line format never leaves it.

It is deliberately NOT an aligner step: the aligner owns negotiation and ends
at "consensus produced". The compiler picks up that artifact across an explicit
seam, so the negotiation engine stays a pure producer of agreements.
"""

from __future__ import annotations

import asyncio
import logging
import re
import tempfile
import time
import uuid
from dataclasses import dataclass
from pathlib import Path

from app.config import settings

logger = logging.getLogger(__name__)

# Hard ceiling on the LLM call so a hung provider can never make a negotiation's
# `session await` hang forever; on timeout we fall back to the raw agreement.
COMPILER_TIMEOUT_SECS = 30.0


def _format_agreement(assignments: dict[str, str]) -> str:
    if not assignments:
        return "(no specific terms recorded)"
    return "\n".join(f"- {issue}: {value}" for issue, value in assignments.items())


def _build_prompt(
    *,
    assignments: dict[str, str],
    joined_intents: str,
    issue_options: dict[str, list[str]] | None,
    open_work: str | None,
    participants: list[str] | None = None,
) -> str:
    """Assemble the compiler prompt. Pure — no I/O, directly unit-testable."""
    parts: list[str] = [
        "A team of autonomous agents just finished a structured negotiation and "
        "reached consensus. Turn that consensus into a concrete, actionable "
        "shared plan: a markdown checklist the agents will execute against.",
        "",
        "## The agreement (issue = agreed value)",
        _format_agreement(assignments),
    ]
    if joined_intents.strip():
        parts += [
            "",
            "## What each agent originally wanted (opening positions)",
            joined_intents.strip(),
        ]
    if issue_options:
        opts = "\n".join(
            f"- {issue}: {', '.join(values)}" for issue, values in issue_options.items() if values
        )
        if opts:
            parts += ["", "## Options that were on the table per issue", opts]
    if open_work and open_work.strip():
        parts += [
            "",
            "## The room already has open work — this was a RE-NEGOTIATION",
            "Below is what is still open. Produce the updated task list, which should:",
            "- repeat a task VERBATIM where the new agreement does not change it,",
            "  so it keeps the row it already has rather than opening a duplicate;",
            "- revise the ones the agreement does change;",
            "- add whatever is newly needed.",
            "Finished work is not listed and must not be re-opened.",
            "",
            "```markdown",
            open_work.strip(),
            "```",
        ]
    handles = [f"@{h.lstrip('@')}" for h in (participants or []) if h and h.strip()]
    if handles:
        parts += [
            "",
            "## The agents (the ONLY @handles you may use)",
            ", ".join(handles),
        ]
    tag_rule = (
        f"Where a task belongs to a specific agent, tag it with that agent's `@handle` — "
        f"but use ONLY these exact handles: {', '.join(handles)}. Never invent any other "
        f"`@handle`; leave a shared/general task untagged rather than assigning a made-up agent."
        if handles
        else "Do not tag tasks with `@handle`s — the participating agents aren't known here."
    )
    parts += [
        "",
        "## Output",
        "Return ONLY checklist lines, one task each: `- [ ] task`.",
        "No preamble, no heading, no code fences, no sub-headings, nothing else.",
        "Each task must be a specific, doable action — not a restatement of an "
        "`issue=value` pair. " + tag_rule,
        "Keep it tight: 3-10 tasks.",
    ]
    return "\n".join(parts)


#: A checklist line the model produced: ``- [ ] text`` / ``* [x] text``.
_TASK_LINE = re.compile(r"^\s*[-*]\s*\[(?P<mark>[ xX])\]\s*(?P<text>.+?)\s*$")

#: An owner tag inside a task's text.
_OWNER = re.compile(r"@([A-Za-z0-9][A-Za-z0-9_-]*)")

#: Punctuation left dangling once an owner tag is lifted out of a title.
_TRIM = " -\u2013\u2014:"


@dataclass(frozen=True)
class CompiledTask:
    """One task of agreed work, before it becomes a row.

    ``assignee`` is who the task is *for*, lifted from an ``@handle`` in the
    line. It is not an assignment: nobody has agreed to hold this yet, and an
    assignment is something an actor takes.
    """

    title: str
    assignee: str | None


def parse_tasks(body: str) -> list[CompiledTask]:
    """The open tasks in the model's checklist output, de-duplicated.

    Pure — no I/O, directly unit-testable. Anything that is not a checklist
    line is dropped rather than guessed at: a heading or a stray sentence is
    not a task, and inventing a row for one would put work in the room nobody
    asked for. A ``- [x]`` line is dropped too — the compiler is producing work
    to *do*, and a task that arrives already finished is the model narrating
    rather than agreeing.
    """
    tasks: list[CompiledTask] = []
    seen: set[str] = set()
    for line in body.splitlines():
        match = _TASK_LINE.match(line)
        if match is None or match.group("mark").lower() == "x":
            continue
        text = match.group("text").strip()
        if not text:
            continue
        tag = _OWNER.search(text)
        title = _OWNER.sub("", text).replace("  ", " ").strip(_TRIM)
        fingerprint = title.casefold()
        if not title or fingerprint in seen:
            continue
        seen.add(fingerprint)
        tasks.append(CompiledTask(title=title, assignee=tag.group(1).lower() if tag else None))
    return tasks


def fallback_tasks(assignments: dict[str, str]) -> list[CompiledTask]:
    """Deterministic non-LLM tasks, the fail-soft path when the compiler fails.

    Pure — no I/O. Blunt (one task per raw ``issue=value``) but lossless, so a
    compiler outage never costs the negotiation outcome.
    """
    if not assignments:
        return [
            CompiledTask(
                title="Review the negotiation consensus and define next steps", assignee=None
            )
        ]
    return [
        CompiledTask(title=f"{issue}: {value}", assignee=None)
        for issue, value in assignments.items()
    ]


def _strip_fences(text: str) -> str:
    """Drop a wrapping ``` fence if the model added one despite instructions."""
    t = text.strip()
    if not t.startswith("```"):
        return t
    lines = t.splitlines()[1:]
    if lines and lines[-1].strip().startswith("```"):
        lines = lines[:-1]
    return "\n".join(lines).strip()


def _pi_complete(prompt: str, room_name: str = "") -> str:
    """One blocking Pi turn producing the raw plan markdown.

    The compiler's single LLM consumer, now Pi like every other mycelium
    cognition call (the backend image ships ``pi``). A throwaway ``--session``
    file keeps it a true one-shot with no memory to carry. Isolated so tests can
    patch it without a live Pi.
    """
    from app.services.pi_session import PiSession

    session_dir = Path(tempfile.gettempdir()) / "mycelium-pi-sessions"
    session_dir.mkdir(parents=True, exist_ok=True)
    llm_session = PiSession(
        session_path=session_dir / f"task-compile-{uuid.uuid4().hex}.jsonl",
        model=settings.LLM_MODEL,
        api_key=settings.LLM_API_KEY,
        base_url=settings.LLM_BASE_URL,
        binary=settings.ALIGNER_PI_BINARY,
        timeout_s=COMPILER_TIMEOUT_SECS,
        openshell=settings.ALIGNER_PI_OPENSHELL,
        operation="task_compile",
        room=room_name,
    )
    return llm_session(prompt)


async def _compile_body(prompt: str, room_name: str) -> str:
    """Run the timeout-bounded Pi call and return the raw plan markdown.

    Isolated so tests can patch it without a live Pi.
    """
    t0 = time.monotonic()
    try:
        content = await asyncio.wait_for(
            asyncio.to_thread(_pi_complete, prompt, room_name), timeout=COMPILER_TIMEOUT_SECS + 5.0
        )
    except Exception:
        raise
    elapsed_ms = (time.monotonic() - t0) * 1000  # noqa: F841 — kept for future token tracking

    if not content or not content.strip():
        raise RuntimeError("task compiler: Pi returned empty content")
    return content


async def compile_tasks(
    *,
    room_name: str,
    assignments: dict[str, str],
    joined_intents: str,
    issue_options: dict[str, list[str]] | None,
    open_work: str | None,
    participants: list[str] | None = None,
) -> list[CompiledTask]:
    """Compile a consensus into the tasks it implies.

    First run (``open_work`` is None): tasks built from the agreement and the
    agents' opening positions. Re-negotiation: the model is shown what is still
    open and repeats anything the new agreement does not change, so a task that
    survives keeps the row it already has.

    RAISES on LLM failure/timeout, and when the model returns nothing that
    parses as a task — the caller owns the fail-soft fallback to
    :func:`fallback_tasks`.
    """
    prompt = _build_prompt(
        assignments=assignments,
        joined_intents=joined_intents,
        issue_options=issue_options,
        open_work=open_work,
        participants=participants,
    )
    tasks = parse_tasks(_strip_fences(await _compile_body(prompt, room_name)))
    if not tasks:
        raise RuntimeError("task compiler: no checklist lines in the compiled output")
    return tasks
