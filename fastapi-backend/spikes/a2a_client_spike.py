#!/usr/bin/env -S uv run --quiet --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["a2a-sdk==1.1.2", "httpx"]
# ///
"""Throwaway spike for issue #712 (epic #719).

Question it answers: is `a2a-sdk` good enough to be the client leg of the
Mycelium A2A bridge, and does the "it's just an await/respond exec loop" thesis
survive contact with a real remote agent?

What it does, against a live A2A agent:
  1. probes BOTH well-known card paths (new /.well-known/agent-card.json and the
     older /.well-known/agent.json) so we know how bad the spec-rename drift is
  2. resolves the Agent Card and prints its skills + capabilities
  3. sends one message via the high-level client and drains the response stream,
     printing every text part it gets back

Default target is the public echo agent. Pass a base URL to hit another.

    uv run fastapi-backend/spikes/a2a_client_spike.py
    uv run fastapi-backend/spikes/a2a_client_spike.py http://localhost:9999
"""

from __future__ import annotations

import asyncio
import sys

import httpx
from a2a.client import A2ACardResolver, ClientConfig, ClientFactory
from a2a.types import Message, Part, Role, SendMessageRequest

NEW_PATH = "/.well-known/agent-card.json"
OLD_PATH = "/.well-known/agent.json"


async def probe_paths(http: httpx.AsyncClient, base: str) -> str | None:
    """Return the first well-known path that serves a card, or None."""
    found: str | None = None
    for path in (NEW_PATH, OLD_PATH):
        try:
            r = await http.get(base.rstrip("/") + path)
            ok = r.status_code == 200 and "json" in r.headers.get("content-type", "")
            print(f"  GET {path} -> {r.status_code} {'OK' if ok else ''}")
            if ok and found is None:
                found = path
        except (httpx.HTTPError, OSError) as exc:  # noqa: PERF203
            print(f"  GET {path} -> error {exc!r}")
    return found


def text_of(msg: Message) -> str:
    return " ".join(p.text for p in msg.parts if p.HasField("text"))


async def run(base: str) -> int:
    print(f"# A2A client spike against {base}\n")
    async with httpx.AsyncClient(timeout=30) as http:
        print("[1] probing well-known card paths")
        path = await probe_paths(http, base)
        if path is None:
            print("no card found at either path; aborting")
            return 1
        print(f"  -> using {path}\n")

        print("[2] resolving Agent Card")
        resolver = A2ACardResolver(http, base, agent_card_path=path)
        card = await resolver.get_agent_card()
        streaming = bool(card.capabilities.streaming)
        skills = ", ".join(s.id for s in card.skills) or "(none)"
        print(f"  name: {card.name}")
        print(f"  version: {card.version}  streaming: {streaming}")
        print(f"  skills: {skills}\n")

        print("[3] send one message + drain the stream")
        # accepted_output_modes must be set: older servers (v1.0.0) treat
        # configuration.acceptedOutputModes as required and reject the call
        # without it. Leaving it empty makes the SDK omit the field -> 400.
        config = ClientConfig(
            httpx_client=http,
            streaming=streaming,
            accepted_output_modes=["text"],
        )
        client = ClientFactory(config).create(card)
        msg = Message(
            message_id="spike-1",
            role=Role.ROLE_USER,
            parts=[Part(text="What can you do? Say hi.")],
        )
        got = 0
        async for resp in client.send_message(SendMessageRequest(message=msg)):
            which = resp.WhichOneof("payload") if hasattr(resp, "WhichOneof") else None
            if resp.HasField("message"):
                got += 1
                print(f"  <- message: {text_of(resp.message)!r}")
            elif resp.HasField("task"):
                print(f"  <- task: id={resp.task.id} state={resp.task.status.state}")
            elif resp.HasField("status_update"):
                print(f"  <- status_update: {resp.status_update.status.state}")
            elif resp.HasField("artifact_update"):
                print("  <- artifact_update")
            else:
                print(f"  <- {which}")
        print(f"\ndrained stream, {got} message payload(s). thesis holds: "
              "resolve card -> send -> read parts, no bespoke protocol code.")
    return 0


if __name__ == "__main__":
    target = sys.argv[1] if len(sys.argv) > 1 else "https://hello-world-gxfr.onrender.com"
    raise SystemExit(asyncio.run(run(target)))
