# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors
"""Rung 0 spike v2 — put back the two things v1 stripped: memory + a brokering mediator.

v1 finding: NEGMAS-drives-and-terminates ✓ and LLM-interprets-prose ✓, but the agents were
amnesiac (fresh isolated call each round, bare offer, no cost-of-no-deal) so the hardliner
never conceded. That's a harness bug, not the model. v2 restores what a real persistent Pi
session + an active mediator would provide:

  1. MEMORY — each agent carries the full running negotiation history (its persistent session).
  2. BROKER — the mediator frames each round: where everyone stands, who hit a hard limit,
     what's actually on offer vs the baseline (the "camp counselor lets everyone speak" *and*
     nudges toward the deal). Not a bare offer relay.
  3. BATNA — no agreement = no rebalance at all, worse for everyone. A deal beats no deal.

Run:
    ANTHROPIC_API_KEY=... uv run --with negmas --with litellm python mediator_spike_v2.py
"""

from __future__ import annotations

import json
import os
import re

import litellm
from negmas import SAOMechanism, make_issue
from negmas.sao import ResponseType, SAONegotiator

MODEL = os.environ.get("SPIKE_MODEL", "anthropic/claude-haiku-4-5-20251001")

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
# The cost of no deal — what v1 lacked. This is what turns a hardliner into a negotiator.
BATNA = (
    "\n\nIMPORTANT: if the team reaches NO agreement, there is NO rebalance at all — the "
    "portfolio stays mis-weighted, the worst outcome for everyone, you included. A compromise "
    "you can live with beats no deal. Protect your ONE hard line; concede everything secondary."
)

HISTORY: list[str] = []


def llm(prompt: str, *, system: str = "", temperature: float = 0.3) -> str:
    msgs = ([{"role": "system", "content": system}] if system else []) + [
        {"role": "user", "content": prompt}
    ]
    resp = litellm.completion(model=MODEL, messages=msgs, temperature=temperature, max_tokens=500)
    return resp.choices[0].message.content or ""


def _json(text: str) -> dict:
    m = re.search(r"\{.*\}", text, re.DOTALL)
    return json.loads(m.group(0)) if m else {}


def discover_issues() -> list[dict]:
    opening = "\n".join(f"@{h}: {p}" for h, p in PERSONAS.items())
    out = _json(
        llm(
            f"You are a negotiation mediator. From the task and each agent's position, identify "
            f"the negotiable ISSUES and 3-4 discrete OPTIONS each.\n\nTASK: {TASK}\n\n"
            f"POSITIONS:\n{opening}\n\n"
            f'Return ONLY JSON: {{"issues":[{{"name":"snake_case","options":["v1","v2"]}}]}}',
            system="Strict JSON. Options are short concrete tokens (e.g. '30' or 'on').",
            temperature=0.0,
        )
    )
    issues = out.get("issues", [])
    if len(issues) < 2:
        raise SystemExit(f"discovery failed: {issues}")
    return issues


def _hist_block() -> str:
    if not HISTORY:
        return "(negotiation just started)"
    return "\n".join(HISTORY[-12:])


def broker(issues: list[dict], offer: tuple | None, round_n: int, cap: int) -> str:
    """The mediator's framing for this round — where everyone stands + a nudge to close."""
    order = ", ".join(i["name"] for i in issues)
    return llm(
        f"You are the negotiation mediator (a neutral camp counselor). It is round {round_n} of "
        f"{cap}. Issue order: {order}. Offer on the table: {offer}.\n\nHistory so far:\n"
        f"{_hist_block()}\n\nWrite 2 sentences to the group: summarize where each agent stands, "
        f"name who has hit a genuine hard limit, and nudge the holdout toward closing — remind "
        f"them a near-deal beats no rebalance. Be concrete and fair, not preachy.",
        system="You are a fair mediator who wants a durable agreement, not to favor anyone.",
    )


def agent_move(
    handle: str, issues: list[dict], offer: tuple | None, proposing: bool, broker_note: str
) -> str:
    space = "; ".join(f"{i['name']} ∈ {{{', '.join(i['options'])}}}" for i in issues)
    order = ", ".join(i["name"] for i in issues)
    role = (
        f"It's your turn to PROPOSE the offer. Current standing offer: {offer}. Propose the offer "
        f"you want (keep or change it) with one line of why."
        if proposing
        else f"The offer on the table is {offer} (order: {order}). ACCEPT or REJECT it, one line why."
    )
    return llm(
        f"You are @{handle} in a live, multi-round negotiation. Issue space: {space}.\n\n"
        f"MEDIATOR: {broker_note}\n\nNegotiation history:\n{_hist_block()}\n\n{role} "
        f"(2 sentences max.)",
        system=PERSONAS[handle] + BATNA,
    )


def interpret(handle: str, prose: str, issues: list[dict], proposing: bool) -> dict:
    order = ", ".join(i["name"] for i in issues)
    schema = (
        '{"action":"counter","offer":{"<issue>":"<option>", ...}}'
        if proposing
        else '{"action":"accept"} OR {"action":"reject"}'
    )
    return _json(
        llm(
            f"Interpret @{handle}'s move into a structured SAO action.\nIssues (order {order}): "
            + "; ".join(f"{i['name']}={i['options']}" for i in issues)
            + f'\n\n@{handle} said:\n"""{prose}"""\n\nReturn ONLY JSON: {schema}. '
            f"Every offer value MUST be one of that issue's options.",
            system="Strict JSON mapping a negotiator's words to an SAO action.",
            temperature=0.0,
        )
    )


class MediatedAgent(SAONegotiator):
    def __init__(self, handle: str, issues: list[dict], cap: int, **kw):
        super().__init__(name=handle, **kw)
        self.handle, self.issues, self.cap = handle, issues, cap
        self._names = [i["name"] for i in issues]
        self._opts = {i["name"]: i["options"] for i in issues}

    def _to_outcome(self, offer: dict) -> tuple | None:
        try:
            vals = tuple(str(offer[n]) for n in self._names)
        except (KeyError, TypeError):
            return None
        return vals if all(vals[k] in self._opts[n] for k, n in enumerate(self._names)) else None

    def propose(self, state, dest=None):
        note = broker(self.issues, state.current_offer, state.step, self.cap)
        prose = agent_move(self.handle, self.issues, state.current_offer, True, note)
        outcome = self._to_outcome(interpret(self.handle, prose, self.issues, True).get("offer", {}))
        outcome = outcome or state.current_offer or tuple(self._opts[n][0] for n in self._names)
        HISTORY.append(f"r{state.step}: @{self.handle} proposed {outcome}")
        print(f"  r{state.step:<2} @{self.handle:<10} PROPOSE      {outcome}")
        return outcome

    def respond(self, state, source=None):
        note = broker(self.issues, state.current_offer, state.step, self.cap)
        prose = agent_move(self.handle, self.issues, state.current_offer, False, note)
        act = interpret(self.handle, prose, self.issues, False).get("action")
        resp = ResponseType.ACCEPT_OFFER if act == "accept" else ResponseType.REJECT_OFFER
        HISTORY.append(f"r{state.step}: @{self.handle} {resp.name} on {state.current_offer}")
        print(f"  r{state.step:<2} @{self.handle:<10} {resp.name:<12} on {state.current_offer}")
        return resp


def main() -> None:
    cap = 20
    print("=== Stage 1: mediator discovers issues/options ===")
    issues = discover_issues()
    for i in issues:
        print(f"  • {i['name']}: {i['options']}")
    negmas_issues = [make_issue(values=[str(v) for v in i["options"]], name=i["name"]) for i in issues]
    mech = SAOMechanism(issues=negmas_issues, n_steps=cap)
    for h in PERSONAS:
        mech.add(MediatedAgent(h, issues, cap))

    print("\n=== v2: memory + brokering mediator + BATNA ===")
    mech.run()

    order = [i["name"] for i in issues]
    print("\n=== Verdict ===")
    if mech.agreement is not None:
        print(f"  AGREEMENT in {mech.current_step} steps: {dict(zip(order, mech.agreement, strict=True))}")
        print("  Terminated at agreement — NEGMAS stopped the moment it was unanimous.")
    else:
        print(f"  NO AGREEMENT after {mech.current_step} steps.")


if __name__ == "__main__":
    main()
