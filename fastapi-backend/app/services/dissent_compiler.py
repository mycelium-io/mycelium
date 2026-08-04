# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""Dissent compiler — produces a structured impasse artifact on broken consensus.

When a negotiation ends without agreement (broken=True), the CFN engine records
*why* negotiation failed but produces no actionable artifact for the operator.
This module fills that gap: it compiles the round state into a markdown document
at ``decisions/unresolved-tensions.md`` that surfaces per-agent positions, the
blocking pattern, and recommended questions for human review.

Mirrors ``plan_compiler.py`` structure: deterministic ``fallback_body`` ships
unconditionally; LLM compilation is optional and time-capped so it never delays
the ``coordination_consensus`` message by more than ``COMPILER_TIMEOUT_SECS``.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

from app.config import settings
from app.services.metrics import record_llm_call

logger = logging.getLogger(__name__)

COMPILER_TIMEOUT_SECS = 30.0
_MAX_TOKENS = 1024


def _model_uses_bedrock_sync_path(model: str | None) -> bool:
    m = (model or "").strip().lower()
    return m.startswith("bedrock/") or "bedrock-runtime" in m or "/bedrock/" in m


async def _acompletion_compat(**kwargs: Any) -> Any:
    """``litellm.acompletion`` for most providers; threaded ``completion`` for Bedrock."""
    import litellm

    model = kwargs.get("model")
    if _model_uses_bedrock_sync_path(model if isinstance(model, str) else None):
        return await asyncio.to_thread(litellm.completion, **kwargs)
    return await litellm.acompletion(**kwargs)


# ── Deterministic fallback ───────────────────────────────────────────────────


def fallback_body(
    *,
    session: str,
    reason: str,
    issues: list[str] | None,
    issue_options: dict[str, list[str]] | None,
    current_offer: dict[str, Any] | None,
    last_actions: dict[str, str],
    last_round_outcome: str,
    joined_intents: str,
    session_handles: list[str],
    round_num: int,
) -> str:
    """Deterministic impasse artifact. No I/O — always succeeds.

    Produces a complete, human-readable document even when the LLM path fails
    or is disabled. All fields are optional so a partial state (e.g. timeout
    before round 1 completed) still produces a useful artifact.
    """
    lines: list[str] = ["# Unresolved Tensions", ""]

    # Summary
    reason_text = {
        "timeout": (
            "Negotiation ended without agreement — either the round budget was "
            "exhausted or agents did not respond in time."
        ),
        "abort": "Negotiation was aborted before agreement was reached.",
    }.get(reason, f"Negotiation ended: {reason}.")
    lines += ["## Summary", "", reason_text, ""]

    # Session context
    lines += [
        f"- **Session:** `{session}`",
        f"- **Rounds completed:** {round_num}",
    ]
    if session_handles:
        lines.append(f"- **Participants:** {', '.join(f'`{h}`' for h in session_handles)}")
    lines.append("")

    # Issues with last offer and positions
    if issues:
        lines += ["## Issues", ""]
        for issue in issues:
            lines.append(f"### {issue}")
            if current_offer and issue in current_offer:
                lines.append(f"- **Last offer on table:** {current_offer[issue]}")
            if issue_options and issue in issue_options and issue_options[issue]:
                lines.append(f"- **Valid options:** {', '.join(issue_options[issue])}")
            lines.append("")

    # Per-agent last actions
    if last_actions:
        lines += ["## Agent positions (last round)", ""]
        for handle, action in sorted(last_actions.items()):
            action_label = {
                "accept": "accepted",
                "reject": "rejected",
                "counter_offer": "counter-offered",
                "timeout": "did not respond (timeout)",
            }.get(action, action)
            lines.append(f"- `{handle}`: {action_label}")
        lines.append("")

    # Blocking pattern
    if last_round_outcome and last_round_outcome not in ("first_round", "agreed"):
        lines += ["## Blocking pattern", "", last_round_outcome.replace("_", " "), ""]

    # Opening positions (excerpt)
    if joined_intents.strip():
        lines += [
            "## Opening positions",
            "",
            joined_intents.strip(),
            "",
        ]

    # Recommended questions for the human reviewer
    lines += [
        "## Recommended questions for human review",
        "",
        "- Which agent's constraint is genuinely non-negotiable vs. a preference?",
        "- Is there an option outside the current option set that satisfies all parties?",
        "- What would change each agent's position — timeline, scope, or risk tolerance?",
        "- Should one agent's constraint take precedence? On what basis?",
        "",
        "_Written by CognitiveEngine — review and amend before routing to session 2._",
    ]

    return "\n".join(lines)


# ── LLM compilation ──────────────────────────────────────────────────────────


def _build_prompt(
    *,
    session: str,
    reason: str,
    issues: list[str] | None,
    issue_options: dict[str, list[str]] | None,
    current_offer: dict[str, Any] | None,
    last_actions: dict[str, str],
    last_round_outcome: str,
    joined_intents: str,
    session_handles: list[str],
    round_num: int,
) -> str:
    """Assemble the dissent compiler prompt. Pure — no I/O."""
    parts: list[str] = [
        "A team of autonomous agents just finished a structured negotiation that "
        "ended WITHOUT agreement. Your job is to produce a structured impasse "
        "artifact for a human operator who will rule on the conflict.",
        "",
        f"Session: {session} | Reason ended: {reason} | Rounds: {round_num}",
    ]

    if session_handles:
        parts += ["", f"Participants: {', '.join(session_handles)}"]

    if issues and current_offer:
        parts += ["", "## Last offer on the table (issue → value)"]
        for issue in issues:
            val = current_offer.get(issue, "(none)")
            parts.append(f"- {issue}: {val}")

    if issues and issue_options:
        parts += ["", "## Valid options per issue"]
        for issue in issues:
            opts = issue_options.get(issue, [])
            if opts:
                parts.append(f"- {issue}: {', '.join(opts)}")

    if last_actions:
        parts += ["", "## Each agent's last action"]
        for handle, action in sorted(last_actions.items()):
            parts.append(f"- {handle}: {action}")

    if last_round_outcome and last_round_outcome not in ("first_round", "agreed"):
        parts += ["", f"## Blocking pattern: {last_round_outcome}"]

    if joined_intents.strip():
        parts += ["", "## Agents' opening positions", joined_intents.strip()]

    parts += [
        "",
        "## Output",
        "Return ONLY the markdown body — no preamble, no code fences.",
        "Start with `# Unresolved Tensions`.",
        "Sections required: Summary (1-2 sentences), Issues (per issue: last offer, "
        "positions, why it's stuck), Blocking pattern (who blocked and why), "
        "Recommended human questions (3-5 bulleted questions the operator should ask "
        "to unlock the impasse).",
        "Be concrete: name the agents, name the values, name the constraint.",
        "Do NOT invent positions not in the data above.",
    ]
    return "\n".join(parts)


def _strip_fences(text: str) -> str:
    t = text.strip()
    if not t.startswith("```"):
        return t
    lines = t.splitlines()[1:]
    if lines and lines[-1].strip().startswith("```"):
        lines = lines[:-1]
    return "\n".join(lines).strip()


async def _compile_dissent_body(prompt: str, session: str) -> str:
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
            operation="dissent_compile",
            model=settings.LLM_MODEL,
            room=session,
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
        operation="dissent_compile",
        model=settings.LLM_MODEL,
        room=session,
        input_tokens=input_tok,
        output_tokens=output_tok,
        cost_usd=cost,
        duration_ms=elapsed_ms,
    )

    content = response.choices[0].message.content
    if not content or not content.strip():
        raise RuntimeError("dissent compiler: LLM returned empty content")
    return content


async def compile_dissent(
    *,
    session: str,
    reason: str,
    issues: list[str] | None,
    issue_options: dict[str, list[str]] | None,
    current_offer: dict[str, Any] | None,
    last_actions: dict[str, str],
    last_round_outcome: str,
    joined_intents: str,
    session_handles: list[str],
    round_num: int,
    use_llm: bool = False,
) -> str:
    """Compile impasse state into a markdown dissent artifact.

    With ``use_llm=False`` (the default) uses the deterministic ``fallback_body``
    — fast, always succeeds, and correct enough for the hackathon. Set
    ``use_llm=True`` to attempt LLM polish; raises on failure so the caller can
    fall back to ``fallback_body``.
    """
    fb_kwargs: dict = {
        "session": session,
        "reason": reason,
        "issues": issues,
        "issue_options": issue_options,
        "current_offer": current_offer,
        "last_actions": last_actions,
        "last_round_outcome": last_round_outcome,
        "joined_intents": joined_intents,
        "session_handles": session_handles,
        "round_num": round_num,
    }
    if not use_llm:
        return fallback_body(**fb_kwargs)

    prompt = _build_prompt(**fb_kwargs)
    body = _strip_fences(await _compile_dissent_body(prompt, session))
    if not body:
        raise RuntimeError("dissent compiler: empty body after cleanup")
    return body
