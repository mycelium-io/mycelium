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
import time
from typing import Any

from app.config import settings
from app.services.metrics import record_llm_call

logger = logging.getLogger(__name__)

# Hard ceiling on the LLM call so a hung provider can never make a negotiation's
# `session await` hang forever — _finish_cfn falls back to the raw agreement.
COMPILER_TIMEOUT_SECS = 30.0
_MAX_TOKENS = 2048


def _model_uses_bedrock_sync_path(model: str | None) -> bool:
    """True when the model must use threaded sync ``completion`` (Bedrock).

    ``litellm.acompletion`` does not work for Bedrock models — Bedrock is sync
    boto3 underneath — so those calls are offloaded to a thread instead. See
    outshift-open/ioc-cfn-cognition-engines PR #19 / commit 85c440c8f.
    """
    m = (model or "").strip().lower()
    return m.startswith("bedrock/") or "bedrock-runtime" in m or "/bedrock/" in m


async def _acompletion_compat(**kwargs: Any) -> Any:
    """``litellm.acompletion`` for most providers; threaded ``completion`` for Bedrock."""
    import litellm

    model = kwargs.get("model")
    if _model_uses_bedrock_sync_path(model if isinstance(model, str) else None):
        return await asyncio.to_thread(litellm.completion, **kwargs)
    return await litellm.acompletion(**kwargs)


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


async def _compile_plan_body(prompt: str, room_name: str) -> str:
    """Run the timeout-bounded LLM call and return the raw plan markdown.

    Isolated so tests can patch it without a live LLM.
    """
    kwargs: dict = {
        "model": settings.LLM_MODEL,
        "max_tokens": _MAX_TOKENS,
        "messages": [{"role": "user", "content": prompt}],
    }
    if settings.LLM_API_KEY:
        kwargs["api_key"] = settings.LLM_API_KEY
    if settings.LLM_BASE_URL:
        kwargs["base_url"] = settings.LLM_BASE_URL

    t0 = time.monotonic()
    try:
        response = await asyncio.wait_for(
            _acompletion_compat(**kwargs), timeout=COMPILER_TIMEOUT_SECS
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

    usage = getattr(response, "usage", None)
    input_tok = (getattr(usage, "prompt_tokens", 0) or 0) if usage else 0
    output_tok = (getattr(usage, "completion_tokens", 0) or 0) if usage else 0
    hidden = getattr(response, "_hidden_params", {}) or {}
    cost = hidden.get("response_cost", 0.0) or 0.0
    record_llm_call(
        operation="plan_compile",
        model=settings.LLM_MODEL,
        room=room_name,
        input_tokens=input_tok,
        output_tokens=output_tok,
        cost_usd=cost,
        duration_ms=elapsed_ms,
    )

    content = response.choices[0].message.content
    if not content or not content.strip():
        raise RuntimeError("plan compiler: LLM returned empty content")
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
