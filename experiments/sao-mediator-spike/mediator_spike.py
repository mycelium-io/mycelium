# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors
"""Rung 0 spike — can an LLM mediator drive a real NEGMAS SAO to a *terminating* agreement?

The unproven core of docs/START_HERE_MEDIATOR.md. No harness, no SLIM, no backend.

The bet: NEGMAS owns the Stacked-Alternating-Offers protocol *and* termination; the LLM only
does what LLMs are good at — turn each agent's natural-language move into a structured
offer/response. We let NEGMAS drive the rounds (its `SAONegotiator.propose/respond` seam), and
inside that seam the "agent" speaks prose (from its persona) which the **mediator interprets**
into a NEGMAS action. If NEGMAS reaches the ~30% tech / 25% other agreement and *stops* — no
restating loop — the concept holds.

Run:
    ANTHROPIC_API_KEY=... uv run --with negmas --with litellm python mediator_spike.py
"""

from __future__ import annotations

import json
import os
import re

import litellm
from negmas import SAOMechanism, make_issue
from negmas.sao import ResponseType, SAONegotiator

MODEL = os.environ.get("SPIKE_MODEL", "anthropic/claude-haiku-4-5-20251001")

# The real ex07 personas (verbatim from the demo agents' manifests). These are the agents'
# *private* preferences — the mediator never sees them; it only sees what they say.
PERSONAS = {
    "growth": (
        "You are GrowthAgent. The portfolio should be tilted toward high-growth technology "
        "stocks. You are willing to accept a diversification rule that caps sector concentration "
        "at 40%, but you will not accept a conservative or balanced allocation that sacrifices "
        "growth. Push for technology sector overweight on every rebalancing decision."
    ),
    "risk": (
        "You are RiskAgent. Volatility must be controlled. The portfolio needs broad "
        "diversification — no single sector above 25%. You are willing to accept modest "
        "technology overweight (up to 30%) if volatility metrics stay within bounds, but you "
        "will block any trade that spikes portfolio beta above the agreed threshold. Concede on "
        "sector cap levels, not on the volatility rule."
    ),
    "execution": (
        "You are ExecutionAgent. The portfolio is out of balance now and the longer we wait the "
        "worse the drift. You want to rebalance immediately using the agreed target weights. You "
        "are flexible on the target itself — that is GrowthAgent and RiskAgent's domain — but you "
        "insist on executing as soon as a target is agreed. Do not delay execution on any "
        "condition that does not directly block the trade."
    ),
}
TASK = (
    "Negotiate the investment-portfolio rebalance. Agree the technology sector cap, the cap on "
    "every other sector, and whether a portfolio-beta gate blocks trades."
)


def llm(prompt: str, *, system: str = "", temperature: float = 0.0) -> str:
    msgs = ([{"role": "system", "content": system}] if system else []) + [
        {"role": "user", "content": prompt}
    ]
    resp = litellm.completion(model=MODEL, messages=msgs, temperature=temperature, max_tokens=600)
    return resp.choices[0].message.content or ""


def _json(text: str) -> dict:
    """Pull the first JSON object out of an LLM reply (tolerant of prose/fences)."""
    m = re.search(r"\{.*\}", text, re.DOTALL)
    return json.loads(m.group(0)) if m else {}


# ── Stage 1: the mediator discovers the negotiable issues + options from the opening ──────────


def discover_issues() -> list[dict]:
    opening = "\n".join(f"@{h}: {p}" for h, p in PERSONAS.items())
    out = _json(
        llm(
            f"You are a negotiation mediator. From the task and each agent's stated position, "
            f"identify the negotiable ISSUES and 3-4 discrete OPTIONS each (concrete values the "
            f"agents could actually agree on).\n\nTASK: {TASK}\n\nPOSITIONS:\n{opening}\n\n"
            f'Return ONLY JSON: {{"issues":[{{"name":"snake_case","options":["v1","v2","v3"]}}]}}',
            system="You output strict JSON. Options must be short concrete tokens (e.g. '30' or "
            "'on'), not sentences.",
        )
    )
    issues = out.get("issues", [])
    if len(issues) < 2:
        raise SystemExit(f"discovery failed — need >=2 issues, got: {issues}")
    return issues


# ── Stage 2: agents speak prose; the mediator interprets it into a NEGMAS action ──────────────


def agent_move(handle: str, issues: list[dict], offer: tuple | None, proposing: bool) -> str:
    """One agent's natural-language move (its real Pi turn would produce this)."""
    space = "; ".join(f"{i['name']} ∈ {{{', '.join(i['options'])}}}" for i in issues)
    order = ", ".join(i["name"] for i in issues)
    if proposing:
        ask = (
            f"It's your turn to PROPOSE the offer on the table. The current standing offer is "
            f"{offer}. State the offer you propose (you may keep it or change it) and one line of "
            f"why. Keep it to 2 sentences."
        )
    else:
        ask = (
            f"The offer on the table is {offer} (order: {order}). Say whether you ACCEPT it or "
            f"REJECT it, and one line of why. Keep it to 2 sentences."
        )
    return llm(
        f"You are @{handle} in a live negotiation. Issue space: {space}.\n{ask}",
        system=PERSONAS[handle],
        temperature=0.3,
    )


def interpret(handle: str, prose: str, issues: list[dict], proposing: bool) -> dict:
    """THE unproven core: natural language -> structured NEGMAS action."""
    order = ", ".join(i["name"] for i in issues)
    schema = (
        '{"action":"counter","offer":{"<issue>":"<option>", ...}}'
        if proposing
        else '{"action":"accept"}  OR  {"action":"reject"}'
    )
    out = _json(
        llm(
            f"You are the mediator interpreting @{handle}'s move into a structured action.\n"
            f"Issues (order: {order}): "
            + "; ".join(f"{i['name']}={i['options']}" for i in issues)
            + f"\n\n@{handle} said:\n\"\"\"{prose}\"\"\"\n\n"
            f"Return ONLY JSON: {schema}. Every offer value MUST be one of that issue's options.",
            system="You output strict JSON mapping a negotiator's words to an SAO action.",
        )
    )
    return out


# ── Stage 3: NEGMAS drives the protocol; each negotiator's move is LLM prose, interpreted ─────


class MediatedAgent(SAONegotiator):
    def __init__(self, handle: str, issues: list[dict], trace: list, **kw):
        super().__init__(name=handle, **kw)
        self.handle = handle
        self.issues = issues
        self.trace = trace
        self._names = [i["name"] for i in issues]
        self._opts = {i["name"]: i["options"] for i in issues}

    def _to_outcome(self, offer: dict) -> tuple | None:
        try:
            vals = tuple(str(offer[n]) for n in self._names)
        except (KeyError, TypeError):
            return None
        if any(vals[k] not in self._opts[n] for k, n in enumerate(self._names)):
            return None  # invalid option -> not a legal outcome (offer_validation analog)
        return vals

    def propose(self, state, dest=None):
        prose = agent_move(self.handle, self.issues, state.current_offer, proposing=True)
        act = interpret(self.handle, prose, self.issues, proposing=True)
        outcome = self._to_outcome(act.get("offer", {})) or state.current_offer or self._fallback()
        self.trace.append((state.step, self.handle, "PROPOSE", outcome, prose.strip()))
        return outcome

    def respond(self, state, source=None):
        prose = agent_move(self.handle, self.issues, state.current_offer, proposing=False)
        act = interpret(self.handle, prose, self.issues, proposing=False)
        resp = ResponseType.ACCEPT_OFFER if act.get("action") == "accept" else ResponseType.REJECT_OFFER
        self.trace.append((state.step, self.handle, resp.name, state.current_offer, prose.strip()))
        return resp

    def _fallback(self) -> tuple:
        return tuple(self._opts[n][0] for n in self._names)


def main() -> None:
    print("=== Stage 1: mediator discovers issues/options ===")
    issues = discover_issues()
    for i in issues:
        print(f"  • {i['name']}: {i['options']}")

    negmas_issues = [make_issue(values=[str(v) for v in i["options"]], name=i["name"]) for i in issues]
    trace: list = []
    mech = SAOMechanism(issues=negmas_issues, n_steps=15)
    for handle in PERSONAS:
        mech.add(MediatedAgent(handle, issues, trace))

    print("\n=== Stage 2-3: NEGMAS drives the SAO; agents speak, mediator interprets ===")
    mech.run()

    order = [i["name"] for i in issues]
    for step, who, act, offer, prose in trace:
        first = prose.splitlines()[0][:88] if prose else ""
        print(f"  r{step:<2} @{who:<10} {act:<14} offer={offer}  “{first}”")

    print("\n=== Verdict ===")
    if mech.agreement is not None:
        agreed = dict(zip(order, mech.agreement, strict=True))
        print(f"  AGREEMENT reached in {mech.current_step} steps (n_steps cap = 15): {agreed}")
        print(f"  Terminated at agreement — {len(trace)} agent moves total, no restating loop.")
    else:
        print(f"  NO AGREEMENT after {mech.current_step} steps — mediator/interpret needs work.")


if __name__ == "__main__":
    main()
