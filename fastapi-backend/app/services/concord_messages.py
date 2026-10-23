# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""The messages a CONCORD run sends, in the elements its specification names.

CONCORD is the IoC team's protocol for agreeing under conflict
(ioc-project.github.io/cognition-protocols/). The conductor plays its
initiator: it sends each member these messages as written, with nothing of
its own before them, and members reply in the matching reply elements
(:mod:`app.services.reply_shape` reads them). Each message's ``instructions``
say what to do and show the reply element to send back, so a member needs no
other copy of the protocol.
"""

from __future__ import annotations

from dataclasses import dataclass
from xml.sax.saxutils import escape as _escape


def _x(value: object) -> str:
    return _escape(str(value), {'"': "&quot;"})


def _el(name: str, value: object, indent: int = 1) -> str:
    return f"{'  ' * indent}<{name}>{_x(value)}</{name}>"


def _number(value: float) -> str:
    return f"{value:g}"


@dataclass
class Candidate:
    id: str
    text: str
    rationale: str = ""


@dataclass
class Scored:
    """One member's score of a candidate, as the repair and commit messages
    show it: normalized 0-1, or ``None`` when the member gave none."""

    agent: str
    score: float | None
    reasoning: str = ""


ANCHOR_REPLY = (
    "<concord-anchor-reply>\n"
    "  <raw_reject>0-100</raw_reject>\n"
    "  <raw_ideal>0-100</raw_ideal>\n"
    "  <note>optional, why</note>\n"
    "</concord-anchor-reply>"
)
CANDIDATE_REPLY = (
    "<concord-candidate-reply>\n"
    "  <candidate>the candidate, in the candidate_schema format</candidate>\n"
    "  <rationale>the facts behind it, and what argues against the alternatives</rationale>\n"
    "</concord-candidate-reply>"
)


def _score_reply(ids: list[str]) -> str:
    lines = ["<concord-score-reply>"]
    for cid in ids:
        lines += [
            f'  <score candidate_id="{_x(cid)}">',
            "    <raw>0-100</raw>",
            "    <reasoning>your full reasoning, including what argues against it</reasoning>",
            "  </score>",
        ]
    lines.append("</concord-score-reply>")
    return "\n".join(lines)


def _reply_with(reply: str) -> list[str]:
    """What follows a message: the reply element to send back."""
    return ["", "Reply with exactly this element, filled in, and nothing else:", "", reply]


def anchor(threshold: float, x_reject: str, x_ideal: str) -> str:
    """ANCHOR, to every member: rate the two reference outcomes."""
    return "\n".join(
        [
            "<concord-anchor>",
            _el("satisfaction_threshold", _number(threshold)),
            _el("x_reject", x_reject),
            _el("x_ideal", x_ideal),
            _el(
                "instructions",
                "Rate the two outcomes above on your own raw 0-100 scale, from your role's "
                "point of view: raw_reject is how satisfied your role would be if x_reject "
                "happened, and should be low; raw_ideal is how satisfied it would be if "
                "x_ideal happened, and has to be higher than raw_reject. Rate the outcomes, "
                "not how things stand now. Every score you give later is on this scale.",
            ),
            "</concord-anchor>",
            *_reply_with(ANCHOR_REPLY),
        ]
    )


def seed(schema: str, threshold: float, context: str) -> str:
    """SEED, to every member: propose one candidate."""
    return "\n".join(
        [
            "<concord-propose-seed>",
            _el("candidate_schema", schema),
            _el("satisfaction_threshold", _number(threshold)),
            _el("context", context),
            _el(
                "instructions",
                "Propose the single candidate that best serves your own role, in the "
                "candidate_schema format. Don't pre-compromise for the other roles: everyone "
                "scores every candidate next. In the rationale, give the facts that support "
                "it and what you know that argues against the alternatives.",
            ),
            "</concord-propose-seed>",
            *_reply_with(CANDIDATE_REPLY),
        ]
    )


def score(context: str, candidates: list[Candidate]) -> str:
    """SCORE, to every member: rate each candidate listed."""
    lines = ["<concord-score>", _el("context", context), "  <candidates>"]
    for c in candidates:
        lines += [f'    <candidate id="{_x(c.id)}">', _el("text", c.text, 3)]
        if c.rationale:
            lines.append(_el("rationale", c.rationale, 3))
        lines.append("    </candidate>")
    lines += [
        "  </candidates>",
        _el(
            "instructions",
            "Rate every candidate on your own raw 0-100 scale, the one you used for the two "
            "outcomes. Copy each candidate id exactly, one score per candidate, in the order "
            "listed, with your full reasoning. Your reasoning is the only way what you know "
            "reaches the others, so say everything that matters, including what argues "
            "against a candidate.",
        ),
        "</concord-score>",
        *_reply_with(_score_reply([c.id for c in candidates])),
    ]
    return "\n".join(lines)


def repair(
    threshold: float,
    schema: str,
    context: str,
    incumbent: Candidate,
    your_score: float,
    scores: list[Scored],
) -> str:
    """REPAIR, to the member who rates the incumbent lowest: propose something new."""
    lines = [
        "<concord-repair>",
        _el("satisfaction_threshold", _number(threshold)),
        _el("candidate_schema", schema),
        _el("context", context),
        f'  <incumbent id="{_x(incumbent.id)}" your_score="{your_score:.2f}" '
        f'shortfall="{max(0.0, threshold - your_score):.2f}">',
        _el("text", incumbent.text, 2),
    ]
    if incumbent.rationale:
        lines.append(_el("rationale", incumbent.rationale, 2))
    lines.append("    <scores>")
    for s in scores:
        value = "" if s.score is None else f' score="{s.score:.2f}"'
        if s.reasoning:
            lines += [
                f'      <score agent="{_x(s.agent)}"{value}>',
                _el("reasoning", s.reasoning, 4),
                "      </score>",
            ]
        else:
            lines.append(f'      <score agent="{_x(s.agent)}"{value}/>')
    lines += [
        "    </scores>",
        "  </incumbent>",
        _el(
            "instructions",
            "You're the member least satisfied with the incumbent. Read it, its rationale, and "
            "every member's score and reasoning, then propose ONE new candidate in the "
            "candidate_schema format: one you would rate near your x_ideal, that doesn't push "
            "the others below the threshold, and that isn't the incumbent or a small change "
            "to it. Your rationale has to answer the strongest reasoning against your "
            "position. The scores shown are normalized 0-1; your own scores stay raw 0-100.",
        ),
        "</concord-repair>",
        *_reply_with(CANDIDATE_REPLY),
    ]
    return "\n".join(lines)


def commit(
    outcome: str,
    winner: Candidate,
    final_scores: list[Scored],
    threshold: float,
) -> str:
    """COMMIT, to every member: how the run ended. No reply."""
    lines = [
        "<concord-commit>",
        _el("outcome", outcome),
        _el("winning_candidate_id", winner.id),
        _el("winning_candidate", winner.text),
        "  <final_scores>",
    ]
    for s in final_scores:
        value = "no-reply" if s.score is None else f"{s.score:.2f}"
        lines.append(f'    <score agent="{_x(s.agent)}" value="{value}"/>')
    lines.append("  </final_scores>")
    short = [s for s in final_scores if s.score is not None and s.score < threshold - 1e-9]
    if short:
        lines.append("  <shortfall>")
        lines += [
            f'    <agent name="{_x(s.agent)}" score="{s.score:.2f}" '
            f'short_by="{threshold - (s.score or 0):.2f}"/>'
            for s in short
        ]
        lines.append("  </shortfall>")
    unknown = [s for s in final_scores if s.score is None]
    if unknown:
        lines.append("  <unknown>")
        lines += [f'    <agent name="{_x(s.agent)}"/>' for s in unknown]
        lines.append("  </unknown>")
    lines.append("</concord-commit>")
    return "\n".join(lines)
