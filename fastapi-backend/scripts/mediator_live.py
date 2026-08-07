# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""Hand-driven live validation of the SAO mediator over a real SLIM node.

Runs the **production** aligner (`AlignerEngine.mediate`) against a running
``slim`` node with the real LLM brain — but the participant agents are *you*:
when the mediator ``@``-addresses an agent, this harness prints the prompt and
reads your typed reply from stdin, then publishes it back over SLIM as that
agent. This validates the whole live loop (discover → NEGMAS SAO → interpret
real prose → terminate at agreement → ``commit:converged``) with **zero token
cost for workers** — only the mediator's own brain spends tokens.

Two gates, one script:
- **Gate A** — ``--brain litellm`` (default): the litellm loop live over SLIM.
- **Gate B** — ``--brain pi``: the Pi brain (``pi`` must be on PATH).

Usage (backend deps on PATH; a slim node on :46357, e.g. `mycelium hub host`
or the dev compose stack)::

    cd fastapi-backend
    uv run python scripts/mediator_live.py                 # Gate A
    uv run python scripts/mediator_live.py --brain pi      # Gate B
    uv run python scripts/mediator_live.py --turn-timeout 300

The scenario is a two-agent portfolio disagreement seeded as opening positions;
override with ``--agents`` / edit ``SCENARIO`` for others. Watch for the payoff:
the mediator reaches agreement and **stops** — no seven-round restating tail.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

# Allow `python scripts/mediator_live.py` from the backend root.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.services import l9
from app.services.l9_models import L9, Kind
from app.services.l9_slim import L9SlimChannel
from app.services.persister import envelope_recipients, envelope_sender
from app.services.room_channels import RoomChannelManager
from app.services.slim_client import (
    DEFAULT_NODE_ENDPOINT,
    SlimClient,
    SlimIdentity,
)

_WORKSPACE = "acme"

# A genuine two-way disagreement — deliberately conflicting opening positions so
# discover_issues has something to structure and the mediator has to broker.
SCENARIO: dict[str, str] = {
    "growth": (
        "We should go aggressive: put 40% of the portfolio into tech to chase the "
        "upside. Anything under 35% tech is leaving returns on the table. I can flex "
        "on the per-sector cap but tech has to be high."
    ),
    "risk": (
        "That's reckless. Tech at 40% concentrates our downside badly. I want tech at "
        "no more than 25%, and a hard 20% cap on every single sector so no one bet can "
        "sink us. Diversification over upside."
    ),
}


def _position_env(sender: str, room: str) -> L9:
    """An agent's opening position / reply — an ``exchange`` the mediator scores."""
    return l9.build_envelope(
        kind=Kind.exchange,
        episode=l9.episode_urn(room, "align"),
        sender=sender,
        sender_role="agent",
        recipients=[l9.SYSTEM_ACTOR_ID],
        topic=l9.topic_urn(room),
        payload_type="reply",
        payload_data={"action": "reply"},
    )


def _summon_env(room: str) -> L9:
    """A human's ``@aligner`` summon (role human → never scored as a position)."""
    return l9.build_envelope(
        kind=Kind.exchange,
        episode=l9.episode_urn(room, "align"),
        sender="human",
        sender_role="human",
        recipients=["aligner"],
        topic=l9.topic_urn(room),
        payload_type="message",
    )


async def _wait(pred, *, timeout: float, label: str) -> None:
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while loop.time() < deadline:
        if pred():
            return
        await asyncio.sleep(0.1)
    msg = f"timed out waiting for: {label}"
    raise TimeoutError(msg)


# A cooperative auto-driver: both agents converge on the conservative numbers
# (25% tech, 20% cap) — values *stated in the openings*, so discover_issues will
# have surfaced them as options and the interpreted outcome is valid. This drives
# a real live negotiation to a clean stop without typing (or worker tokens).
_COMPROMISE = "25% tech and a hard 20% cap on every sector"


def _auto_reply(prompt: str) -> str:
    if "PROPOSE" in prompt or "state the offer" in prompt.lower():
        return f"I propose {_COMPROMISE} — a fair middle we can all live with."
    # Responding: accept the *table* offer as-is (no contradictory numbers) so a
    # clean unanimous stop is unambiguous.
    return "I accept the offer on the table exactly as it stands. Let's lock it and move on."


async def _agent_loop(
    handle: str, channel: L9SlimChannel, room: str, stop: asyncio.Event, *, auto: bool
) -> None:
    """Hand-drive one agent: when the mediator prompts it, supply the reply.

    Interactive by default (reads your typed reply from stdin); ``auto`` uses a
    canned cooperative reply so the loop can run non-interactively.
    """
    while not stop.is_set():
        try:
            released, _arrived, _ctx = await channel.receive_with_context(timeout_s=1.0)
        except Exception:
            continue
        for env, content in released:
            data = env.payload.data if env.payload is not None else {}
            # DIAGNOSTIC: log every envelope this client actually receives.
            print(
                f"   ·[recv @{handle}] kind={env.header.kind.value} "
                f"action={(data or {}).get('action')!r} "
                f"from={envelope_sender(env)!r} to={envelope_recipients(env)}",
                file=sys.stderr,
            )
            if env.header.kind != Kind.exchange:
                continue
            # Only the mediator's turn-prompt carries action == "position".
            if (data or {}).get("action") != "position":
                continue
            if handle not in envelope_recipients(env):
                continue
            prompt = content.get("content") or "(no prompt text)"
            print(f"\n{'=' * 70}\n📨  MEDIATOR → @{handle}:\n{prompt}\n{'-' * 70}")
            if auto:
                reply = _auto_reply(prompt)
                print(f"🤖  auto-reply as @{handle}> {reply}")
            else:
                reply = await asyncio.to_thread(input, f"✍️  reply as @{handle}> ")
            await channel.send(_position_env(handle, room), extra={"content": reply})
            print(f"   ↳ sent @{handle}'s reply.")


async def main() -> int:
    parser = argparse.ArgumentParser(description="Hand-driven live SAO mediator validation.")
    parser.add_argument("endpoint", nargs="?", default=DEFAULT_NODE_ENDPOINT)
    parser.add_argument("--brain", choices=["litellm", "pi"], default="litellm")
    parser.add_argument("--room", default="mediator-live")
    parser.add_argument("--agents", nargs="*", default=list(SCENARIO))
    parser.add_argument("--turn-timeout", type=float, default=300.0)
    parser.add_argument("--max-steps", type=int, default=12)
    parser.add_argument(
        "--auto", action="store_true", help="canned cooperative replies (non-interactive)"
    )
    args = parser.parse_args()

    import logging

    logging.basicConfig(
        level=logging.INFO, format="  [log] %(name)s: %(message)s", stream=sys.stderr
    )
    logging.getLogger("slim").setLevel(logging.WARNING)

    from app.services.aligner import AlignerEngine

    handles = args.agents
    print(f"→ endpoint={args.endpoint}  room={args.room}  brain={args.brain}  agents={handles}")

    manager = RoomChannelManager(endpoint=args.endpoint, default_workspace=_WORKSPACE)
    engine = AlignerEngine(
        manager,
        handle="aligner",
        threshold=0.6,
        round_timeout_s=args.turn_timeout,
        max_steps=args.max_steps,
        brain=args.brain,
    )
    manager.on_summon = engine.handle_summon  # wire BEFORE provision
    managed = await manager.provision(args.room)
    if managed is None or managed.persister is None:
        print("✗ could not provision a SLIM channel — is the node reachable?")
        return 1
    persister = managed.persister

    channels: dict[str, L9SlimChannel] = {}
    clients: list[SlimClient] = []
    for h in handles:
        client = await SlimClient(SlimIdentity(_WORKSPACE, args.room, h)).connect(args.endpoint)
        clients.append(client)
        listen = asyncio.create_task(client.listen_for_session())
        await manager.invite(args.room, h)
        channels[h] = L9SlimChannel(client, await listen)

    stop = asyncio.Event()
    try:
        await _wait(
            lambda: set(handles) <= set(manager.members(args.room)),
            timeout=15.0,
            label="all agents joined the channel",
        )

        # Seed the conflicting opening positions.
        print("\n— seeding opening positions —")
        for h in handles:
            print(f"  @{h}: {SCENARIO.get(h, '(none)')}")
            await channels[h].send(
                _position_env(h, args.room), extra={"content": SCENARIO.get(h, "")}
            )
        await _wait(
            lambda: {_norm(r.sender) for r in persister.log.records} >= {_norm(h) for h in handles},
            timeout=15.0,
            label="opening positions recorded",
        )

        # Start the hand-drive loops, then summon the mediator.
        loops = [
            asyncio.create_task(_agent_loop(h, channels[h], args.room, stop, auto=args.auto))
            for h in handles
        ]
        print("\n— summoning @aligner (the mediator takes the wheel) —\n")
        await channels[handles[0]].send(
            _summon_env(args.room), extra={"content": "@aligner please help us converge"}
        )

        # Watch for the terminal commit on any channel.
        commit = await _watch_for_commit(channels, timeout=args.turn_timeout * args.max_steps + 60)
        stop.set()
        for loop_task in loops:
            loop_task.cancel()

        if commit is None:
            print("\n✗ no commit envelope observed within the budget.")
            return 1
        _report(commit, persister)
        return 0
    finally:
        stop.set()
        for client in clients:
            await client.close()
        await manager.close_all()


def _norm(s: str) -> str:
    return (s or "").strip().lstrip("@").lower()


async def _watch_for_commit(channels: dict[str, L9SlimChannel], *, timeout: float) -> L9 | None:
    """Return the first ``commit`` envelope any participant receives, or None."""

    async def _one(channel: L9SlimChannel) -> L9 | None:
        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout
        while loop.time() < deadline:
            try:
                for env in await channel.receive(timeout_s=2.0):
                    if env.header.kind == Kind.commit:
                        return env
            except Exception:
                continue
        return None

    tasks = [asyncio.create_task(_one(c)) for c in channels.values()]
    try:
        for fut in asyncio.as_completed(tasks):
            result = await fut
            if result is not None:
                return result
        return None
    finally:
        for task in tasks:
            task.cancel()


def _report(
    commit: L9, persister
) -> None:  # persister is a RoomPersister, left untyped to avoid an import cycle
    data = commit.payload.data if commit.payload is not None else {}
    print(f"\n{'=' * 70}\n🏁  RESULT")
    print(f"  subkind    : {commit.header.subkind}")
    print(f"  assignments: {data.get('assignments')}")
    print(f"  metrics    : {data.get('metrics')}")
    print(f"{'-' * 70}\n📜  TRANSCRIPT (the bounded negotiation):")
    for i, record in enumerate(persister.log.records, 1):
        sender = record.sender or "?"
        text = (record.content.get("content") or "").replace("\n", " ")
        print(f"  {i:2d}. @{sender:<9} {text[:96]}")
    n_exchanges = sum(1 for r in persister.log.records if r.kind == "exchange")
    print(
        f"{'-' * 70}\n  {n_exchanges} exchange messages total — watch that it STOPPED at agreement."
    )


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
