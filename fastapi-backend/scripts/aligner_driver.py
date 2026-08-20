"""Interactive in-process aligner driver — real Pi brain, no SLIM, no node.

Runs the *real* mediator cognition (``discover_issues`` -> ``MediatedNegotiation``
-> ``build_mechanism`` -> ``mech.run``) with a real per-session ``PiBrain``, but
replaces only the agent-reply seam (``fetch_prose``) with a file bridge so a human
(or Claude) can answer as each agent, turn by turn. The episode is recorded via the
real ``l9_episode`` folding, so afterwards you can inspect exactly what the aligner
understood and what the wire envelopes look like.

This isolates the aligner's *cognition* from the SLIM transport (which needs live
subscriber connectors). It's the rig for gut-checking mediator-logic changes
(#679/#680/#682/#683) against a real model.

Protocol (all under --workdir, default /tmp/aligner-lab):
  * The driver writes the current turn to ``turn.json`` and blocks.
  * You read ``turn.json``, then write the agent's reply prose to ``reply.txt``.
  * The driver consumes ``reply.txt`` (deletes it) and continues.
  * On termination it writes ``result.json`` (assignments + metrics + transcript).

Positions are seeded from ``positions.json`` in the workdir ({handle: prose}); if
absent, a default two-agent budget scenario is used.

Run from fastapi-backend/:
  uv run python scripts/aligner_driver.py --workdir /tmp/aligner-lab
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import time
from pathlib import Path

from app.services import l9_episode, mediator
from app.services.pi_brain import PiBrain


def _load_llm_env() -> dict[str, str]:
    """Read LLM_MODEL/API_KEY/BASE_URL from ~/.mycelium/.env (never printed)."""
    env_path = Path.home() / ".mycelium" / ".env"
    out: dict[str, str] = {}
    if env_path.is_file():
        for line in env_path.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            if k in {"LLM_MODEL", "LLM_API_KEY", "LLM_BASE_URL"}:
                out[k] = v.strip()
    # Env vars win over the file if the caller exported them.
    for k in ("LLM_MODEL", "LLM_API_KEY", "LLM_BASE_URL"):
        if os.environ.get(k):
            out[k] = os.environ[k]
    return out


_DEFAULT_POSITIONS = {
    "growth": "Allocate 60% of the budget to the tech platform rebuild; growth depends on it. Ship in Q3.",
    "risk": "Tech gets at most 30%; the rest to compliance and reserves. Q4 timeline is safer.",
}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--workdir", default="/tmp/aligner-lab")
    ap.add_argument(
        "--task", default="Converge on the tech budget percentage and the ship timeline."
    )
    ap.add_argument("--cap", type=int, default=30, help="max SAO steps")
    ap.add_argument(
        "--turn-timeout", type=float, default=3600.0, help="seconds to wait for a reply"
    )
    args = ap.parse_args()

    work = Path(args.workdir)
    work.mkdir(parents=True, exist_ok=True)
    turn_file = work / "turn.json"
    reply_file = work / "reply.txt"
    result_file = work / "result.json"
    for stale in (turn_file, reply_file, result_file):
        stale.unlink(missing_ok=True)

    pos_file = work / "positions.json"
    positions = json.loads(pos_file.read_text()) if pos_file.is_file() else dict(_DEFAULT_POSITIONS)
    participants = list(positions)

    llm_env = _load_llm_env()
    if not llm_env.get("LLM_MODEL"):
        raise SystemExit("no LLM_MODEL found in ~/.mycelium/.env or environment")

    session_dir = work / "pi-session"
    session_dir.mkdir(exist_ok=True)
    brain = PiBrain(
        session_path=session_dir / "brain.jsonl",
        model=llm_env["LLM_MODEL"],
        api_key=llm_env.get("LLM_API_KEY"),
        base_url=llm_env.get("LLM_BASE_URL"),
        binary="pi",
        timeout_s=180.0,
        openshell=False,
    )

    ep = l9_episode.open_episode(
        parent_room="aligner-lab",
        short_id="drv00001",
        workspace_id="mycelium",
        mas_id="",
        agents=participants,
        joined_intents="\n".join(f"- {h}: {p}" for h, p in positions.items()),
        engine_handle="aligner",
        opening_positions=positions,
    )

    print(f"[driver] model={llm_env['LLM_MODEL']}  participants={participants}", flush=True)

    seq = {"n": 0}

    def ask(handle: str, prompt: str, round_n: int) -> str:
        """Blocking form of the file bridge, for turns outside the async run."""
        return asyncio.run(fetch_prose(handle, prompt, round_n))

    async def fetch_prose(handle: str, prompt: str, round_n: int) -> str:
        """Interactive agent-reply seam: publish the turn, block on reply.txt."""
        seq["n"] += 1
        turn_file.write_text(
            json.dumps(
                {"seq": seq["n"], "handle": handle, "round": round_n, "prompt": prompt},
                indent=2,
            )
        )
        print(
            f"\n[driver] === TURN {seq['n']} — @{handle} (round {round_n}) ===\n"
            f"[driver] aligner asks:\n{prompt}\n"
            f"[driver] >>> write @{handle}'s reply to {reply_file} <<<",
            flush=True,
        )
        deadline = time.monotonic() + args.turn_timeout
        while time.monotonic() < deadline:
            if reply_file.exists():
                text = reply_file.read_text().strip()
                reply_file.unlink(missing_ok=True)
                turn_file.unlink(missing_ok=True)
                print(f"[driver] @{handle} replied: {text}", flush=True)
                return text
            await asyncio.sleep(0.5)
        print(f"[driver] @{handle} timed out (no reply) — treating as silence.", flush=True)
        return ""

    print("[driver] checking the opening positions for term mismatch (real LLM)...", flush=True)
    mismatches = mediator.detect_term_mismatch(positions, llm=brain)
    clarifications: dict[str, str] = {}
    if mismatches:
        print(
            f"[driver] term mismatch = {json.dumps(mismatches)} — one clarifying round", flush=True
        )
        for handle in list(positions):
            reply = ask(handle, mediator.clarification_prompt(handle, mismatches), 0).strip()
            if not reply:
                continue
            clarifications[handle] = reply
            positions[handle] = f"{positions[handle]}\n\n(clarified by @{handle}: {reply})"
        l9_episode.record_term_check(ep, mismatches=mismatches, clarifications=clarifications)
    else:
        print("[driver] no term mismatch — negotiating on the opening positions", flush=True)

    print("[driver] discovering issues from opening positions (real LLM)...", flush=True)
    issues = mediator.discover_issues(args.task, positions, llm=brain)
    print(f"[driver] issues = {json.dumps(issues)}", flush=True)
    if not issues:
        result_file.write_text(json.dumps({"converged": False, "reason": "no issues discovered"}))
        print("[driver] no issues discovered; done.", flush=True)
        return

    async def run() -> None:
        loop = asyncio.get_running_loop()
        negotiation = mediator.MediatedNegotiation(
            issues=issues,
            cap=args.cap,
            loop=loop,
            fetch_prose=fetch_prose,
            turn_timeout_s=args.turn_timeout,
            llm=brain,
            on_reading=lambda handle, reading, proposing: l9_episode.record_reply(
                ep,
                handle=handle,
                reply=_reading_to_reply(reading, proposing),
                round_n=None,
            ),
        )
        mech = mediator.build_mechanism(issues, participants, negotiation, cap=args.cap)
        await asyncio.to_thread(mech.run)
        assignments = mediator.agreement_assignments(mech, negotiation.names)
        metrics = l9_episode.compute_metrics(ep)
        result = {
            "converged": assignments is not None,
            "assignments": assignments,
            "steps": mech.current_step,
            "metrics": metrics,
            "issues": issues,
            "opening_positions": ep.opening_positions,
            "term_mismatches": ep.term_mismatches,
            "clarifications": ep.clarifications,
            "episode_messages": ep.messages,
        }
        result_file.write_text(json.dumps(result, indent=2))
        print(
            f"\n[driver] === DONE — {'AGREEMENT' if assignments else 'no agreement'} "
            f"in {mech.current_step} steps ===\n[driver] assignments={assignments}\n"
            f"[driver] metrics={metrics}\n[driver] full result + episode transcript -> {result_file}",
            flush=True,
        )

    asyncio.run(run())


def _reading_to_reply(reading: dict, proposing: bool) -> dict:
    """Mirror aligner._fold_reading: derive the metric action + wire move (#681)."""
    reply: dict = {}
    action = reading.get("action") if isinstance(reading, dict) else None
    if isinstance(action, str) and action:
        reply["action"] = "accept" if action == "accept" else "reject"
    offer = reading.get("offer") if isinstance(reading, dict) else None
    if isinstance(offer, dict):
        reply["offer"] = offer
        reply.setdefault("action", "accept" if proposing else "reject")
    from app.services import l9

    if isinstance(action, str) and action in l9.EXCHANGE_MOVE_SUBKINDS:
        reply["move"] = action
    elif isinstance(offer, dict):
        reply["move"] = "counter"
    return reply


if __name__ == "__main__":
    main()
