#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors
"""
Dissent-map demo agent simulator.

Runs the full arc for one persona:
  Session 1: join → negotiate (conflicting positions) → impasse
  Wait:       poll for human ruling in room memory
  Session 2:  join → negotiate (accept toward consensus) → plan

Usage:
    python demo-agent.py --persona sre-agent --room dissent-map-demo
    python demo-agent.py --persona secops-agent --room dissent-map-demo
    python demo-agent.py --persona pm-agent --room dissent-map-demo
    python demo-agent.py --persona eng-lead --room dissent-map-demo
"""

import argparse
import json
import subprocess
import sys
import time

# ── Persona definitions ────────────────────────────────────────────────────────

PERSONAS: dict[str, dict] = {
    "sre-agent": {
        "handle": "sre-agent",
        "s1_intent": (
            "Will support a Friday ship only if checkout is behind a kill switch. "
            "Hard constraint: must be reversible in under 2 minutes — "
            "anything slower lets bad orders compound and downstream systems go inconsistent."
        ),
        # Keywords to prefer when picking from issue_options in session 1
        "prefer": ["kill switch", "feature flag", "reversible", "2 min", "fast rollback"],
        # Keywords to avoid (lean toward conflict)
        "avoid": ["no rollback", "no kill switch", "complex rollback", "manual recovery", "ship as-is"],
    },
    "secops-agent": {
        "handle": "secops-agent",
        "s1_intent": (
            "Cannot sign the release until we confirm the checkout bug is not exploitable. "
            "Hard constraint: a discount-code edge case that corrupts order totals is a textbook "
            "attack surface — ship before investigation and we may be shipping a known exploit."
        ),
        "prefer": ["investigate", "security review", "confirm not exploitable", "test first", "hold"],
        "avoid": ["ship as-is", "ship friday", "workaround", "skip review", "no investigation"],
    },
    "pm-agent": {
        "handle": "pm-agent",
        "s1_intent": (
            "Ship Friday — the launch is announced, the marketing campaign goes live Friday morning, "
            "and our enterprise customer has this feature in their MSA. "
            "Hard constraint: slipping means cancelling a paid campaign and triggering an SLA penalty."
        ),
        "prefer": ["ship friday", "launch", "proceed", "friday", "dark launch", "controlled rollout"],
        "avoid": ["slip", "delay", "postpone", "next week", "cancel launch"],
    },
    "eng-lead": {
        "handle": "eng-lead",
        "s1_intent": (
            "Do not ship until the bug is fixed and staging passes. "
            "Hard constraint: this bug corrupts order metadata in ~3% of discount-code orders — "
            "shipping known data corruption is a liability regardless of timeline pressure."
        ),
        "prefer": ["fix first", "slip", "staging", "regression", "patch", "next week"],
        "avoid": ["ship with bug", "ship as-is", "workaround", "smoke only", "skip staging"],
    },
}

# ── CLI helpers ────────────────────────────────────────────────────────────────

def run(args: list[str], check: bool = False) -> tuple[str, int]:
    result = subprocess.run(
        ["mycelium"] + args,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip(), result.returncode


def join_session(handle: str, room: str, intent: str, session_num: int) -> bool:
    print(f"[{handle}] Joining session {session_num}…")
    out, rc = run(["session", "join", "-H", handle, "-m", intent, "--room", room])
    if rc != 0:
        print(f"[{handle}] Join failed (rc={rc}): {out[:120]}")
        return False
    return True


def await_event(handle: str, room: str, timeout: int = 180) -> dict:
    out, _ = run(["session", "await", "-H", handle, "--room", room, "--timeout", str(timeout)])
    try:
        return json.loads(out)
    except json.JSONDecodeError:
        return {"type": "unknown", "raw": out}


def respond(handle: str, room: str, action: str) -> None:
    args = ["negotiate", "respond", action, "--room", room, "-H", handle]
    out, rc = run(args)
    if rc != 0:
        print(f"[{handle}] respond {action} failed (rc={rc}): {out[:120]}")


def get_memory(key: str, room: str) -> str:
    out, _ = run(["memory", "get", key, "--room", room])
    return out


# ── Negotiation logic ──────────────────────────────────────────────────────────

def negotiate(
    handle: str,
    room: str,
    session_num: int,
) -> tuple[bool, str | None]:
    """
    Run one session's negotiation loop.

    Session 1: reject every tick — each agent holds their hard position.
    Session 2: accept every tick — ruling constrains the space, convergence follows.

    Returns (broken, dissent_file).
    """
    round_count = 0
    while True:
        event = await_event(handle, room)
        t = event.get("type")

        if t == "consensus":
            broken = bool(event.get("broken"))
            dissent_file = event.get("dissent_file")
            if broken:
                print(
                    f"[{handle}] Impasse after {round_count} round(s). "
                    f"Dissent artifact: {dissent_file}"
                )
            else:
                print(
                    f"[{handle}] Consensus! Plan: {event.get('plan_file')} "
                    f"| Assignments: {event.get('assignments')}"
                )
            return broken, dissent_file

        if t == "tick":
            round_count += 1
            rnd = event.get("round", "?")
            if session_num == 1:
                print(f"[{handle}] S1 round {rnd}: rejecting")
                respond(handle, room, "reject")
            else:
                print(f"[{handle}] S2 round {rnd}: accepting")
                respond(handle, room, "accept")

        if t == "unknown":
            raw = event.get("raw", "")
            if raw:
                print(f"[{handle}] Unexpected output: {raw[:120]}")
            time.sleep(2)


def wait_for_ruling(handle: str, room: str, poll_interval: int = 10) -> str:
    """Poll room memory until a human ruling is written, then return it."""
    print(f"[{handle}] Waiting for human ruling at decisions/human-ruling …")
    while True:
        ruling = get_memory("decisions/human-ruling", room)
        if ruling and not ruling.startswith("Error") and "not found" not in ruling.lower():
            print(f"[{handle}] Ruling found: {ruling[:120]}…")
            return ruling
        time.sleep(poll_interval)


# ── Main ───────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="Dissent-map demo agent")
    parser.add_argument("--persona", required=True, choices=list(PERSONAS), help="Agent persona")
    parser.add_argument("--room", default="dissent-map-demo", help="Room name")
    parser.add_argument("--poll-interval", type=int, default=10, help="Ruling poll interval (s)")
    args = parser.parse_args()

    persona = PERSONAS[args.persona]
    handle = persona["handle"]
    room = args.room

    print(f"[{handle}] Demo agent started. Room: {room}")
    print(f"[{handle}] Session 1 intent: {persona['s1_intent'][:80]}…")

    # ── Session 1 ──────────────────────────────────────────────────────────────
    if not join_session(handle, room, persona["s1_intent"], session_num=1):
        sys.exit(1)

    broken, _ = negotiate(handle, room, session_num=1)

    if not broken:
        # Early consensus — nothing more to do
        sys.exit(0)

    # ── Wait for human ruling ──────────────────────────────────────────────────
    ruling = wait_for_ruling(handle, room, poll_interval=args.poll_interval)

    # ── Session 2 ──────────────────────────────────────────────────────────────
    # Agents join with ruling embedded in their opening intent.
    # If operator already clicked "START SESSION 2", join finds it.
    # If not, join auto-creates session 2 — either path works.
    s2_intent = (
        f"Ruling acknowledged: {ruling[:300]}. "
        f"I accept the framework and am ready to converge within these constraints."
    )

    print(f"[{handle}] Joining session 2…")
    joined = False
    while not joined:
        joined = join_session(handle, room, s2_intent, session_num=2)
        if not joined:
            time.sleep(args.poll_interval)

    broken2, _ = negotiate(handle, room, session_num=2)
    if broken2:
        print(f"[{handle}] Session 2 also ended in impasse. Human intervention needed.")
        sys.exit(2)

    print(f"[{handle}] Done.")


if __name__ == "__main__":
    main()
