# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""Plan compiler — turns a negotiation consensus into a room plan.

When structured negotiation reaches consensus, the aligner produces a flat
``issue=value`` agreement dict. That records *what was agreed* but is not an
actionable plan. This module is a separate stage that *consumes* that consensus
and compiles it — via one LLM call — into a markdown checklist materialized at
``plan/tasks.md``.

It is deliberately NOT an aligner step: the aligner owns negotiation and ends
at "consensus produced". The compiler picks up that artifact across an explicit
seam, so the negotiation engine stays a pure producer of agreements.
"""

from __future__ import annotations

import asyncio
import logging
import tempfile
import time
import uuid
from pathlib import Path

from app.config import settings
from app.services.metrics import record_llm_call

logger = logging.getLogger(__name__)

# Hard ceiling on the LLM call so a hung provider can never make a negotiation's
# `session await` hang forever — _finish_cfn falls back to the raw agreement.
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
    existing_plan: str | None,
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
    if existing_plan and existing_plan.strip():
        parts += [
            "",
            "## The room already has a plan — this was a RE-NEGOTIATION",
            "Below is the current plan. Produce an UPDATED plan that:",
            "- preserves every completed task (`- [x]`) EXACTLY as written, verbatim;",
            "- revises the open tasks (`- [ ]`) to match the new agreement;",
            "- keeps the same overall structure.",
            "",
            "```markdown",
            existing_plan.strip(),
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
        "Return ONLY the markdown body of the plan — no preamble, no code fences.",
        "Start with a single `# ` heading naming the plan.",
        "Then list concrete next steps as GitHub-style checklist lines: `- [ ] task`.",
        "Each task must be a specific, doable action — not a restatement of an "
        "`issue=value` pair. " + tag_rule,
        "Keep it tight: 3-10 tasks. No sub-headings unless genuinely needed.",
    ]
    return "\n".join(parts)


def fallback_body(assignments: dict[str, str]) -> str:
    """Deterministic non-LLM plan body. Used by _finish_cfn when the compiler fails.

    Pure — no I/O. Ugly (one line per raw ``issue=value``) but lossless, so a
    compiler outage never costs the negotiation outcome.
    """
    lines = ["# Plan", ""]
    if assignments:
        lines += [f"- [ ] {issue}: {value}" for issue, value in assignments.items()]
    else:
        lines.append("- [ ] Review the negotiation consensus and define next steps")
    return "\n".join(lines)


def _strip_fences(text: str) -> str:
    """Drop a wrapping ``` fence if the model added one despite instructions."""
    t = text.strip()
    if not t.startswith("```"):
        return t
    lines = t.splitlines()[1:]
    if lines and lines[-1].strip().startswith("```"):
        lines = lines[:-1]
    return "\n".join(lines).strip()


def _pi_complete(prompt: str) -> str:
    """One blocking Pi turn producing the raw plan markdown.

    The compiler's single LLM consumer, now Pi like every other mycelium
    cognition call (the backend image ships ``pi``). A throwaway ``--session``
    file keeps it a true one-shot with no memory to carry. Isolated so tests can
    patch it without a live Pi.
    """
    from app.services.pi_brain import PiBrain

    session_dir = Path(tempfile.gettempdir()) / "mycelium-pi-sessions"
    session_dir.mkdir(parents=True, exist_ok=True)
    brain = PiBrain(
        session_path=session_dir / f"plan-compile-{uuid.uuid4().hex}.jsonl",
        model=settings.LLM_MODEL,
        api_key=settings.LLM_API_KEY,
        base_url=settings.LLM_BASE_URL,
        binary=settings.ALIGNER_PI_BINARY,
        timeout_s=COMPILER_TIMEOUT_SECS,
        openshell=settings.ALIGNER_PI_OPENSHELL,
    )
    return brain(prompt)


async def _compile_plan_body(prompt: str, room_name: str) -> str:
    """Run the timeout-bounded Pi call and return the raw plan markdown.

    Isolated so tests can patch it without a live Pi.
    """
    t0 = time.monotonic()
    try:
        content = await asyncio.wait_for(
            asyncio.to_thread(_pi_complete, prompt), timeout=COMPILER_TIMEOUT_SECS + 5.0
        )
    except Exception:
        record_llm_call(
            operation="plan_compile",
            model=settings.LLM_MODEL,
            room=room_name,
            error=True,
        )
        raise
    elapsed_ms = (time.monotonic() - t0) * 1000

    # Pi does not report per-turn token usage or cost on its JSON stream, so only
    # the call count + latency are recorded (tokens/cost stay zero).
    record_llm_call(
        operation="plan_compile",
        model=settings.LLM_MODEL,
        room=room_name,
        duration_ms=elapsed_ms,
    )

    if not content or not content.strip():
        raise RuntimeError("plan compiler: Pi returned empty content")
    return content


async def compile_plan(
    *,
    room_name: str,
    assignments: dict[str, str],
    joined_intents: str,
    issue_options: dict[str, list[str]] | None,
    existing_plan: str | None,
    participants: list[str] | None = None,
) -> str:
    """Compile a consensus into a full markdown body for ``plan/tasks.md``.

    First run (``existing_plan`` is None): a fresh ``# `` checklist built from
    the agreement and the agents' opening positions. Re-negotiation: a merge
    that preserves completed ``- [x]`` tasks verbatim and revises open ones.

    RAISES on LLM failure/timeout — the caller (``_finish_cfn``) owns the
    fail-soft fallback to :func:`fallback_body`.
    """
    prompt = _build_prompt(
        assignments=assignments,
        joined_intents=joined_intents,
        issue_options=issue_options,
        existing_plan=existing_plan,
        participants=participants,
    )
    body = _strip_fences(await _compile_plan_body(prompt, room_name))
    if not body:
        raise RuntimeError("plan compiler: empty plan body after cleanup")
    return body
