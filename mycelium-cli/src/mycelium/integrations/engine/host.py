# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""Host-side engine dispatch — connector reuses its session to run NEGMAS on the host.

When ``ENGINE_RUNTIME=host``, a registered ``engine`` gets a daemon connector
like any cold-spawn agent. On an ``@``-summon the connector does *not* cold-spawn
a subprocess — it runs the NEGMAS drive loop (:mod:`mycelium.engine.runtime`)
**on the host**, where ``pi`` lives. This module is the glue between the
connector and that drive:

- :func:`dispatch_engine` is the entry the connector calls on an engine wake. It
  registers a "drive-active" inbound queue on the daemon state, wraps the
  connector's own ``publish`` + that queue as an :class:`EngineChannel`, sources
  the roster + opening prose + brain, runs one negotiation, and deregisters.
- While the drive is active, the connector's receive loop routes inbound agent
  replies (addressed to the engine) into the queue instead of re-dispatching —
  so the drive reads real replies over the connector's existing session, with no
  second SLIM connection and reusing the membership/invite that already works.

The roster is read from the **local mirror** (no HTTP); the opening prose is read
from the backend's ``/messages`` API (the host has no transcript of its own). The
brain is built from the **host** LLM config — the whole point of relocating the
runtime off the backend container.
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING, Any

import httpx

from mycelium.daemon.dispatch import list_agent_handles, load_manifest

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from mycelium.config import MyceliumConfig
    from mycelium.daemon.state import DaemonState

log = logging.getLogger("mycelium.daemon")

# Default drive knobs — mirror the backend aligner settings so a host run behaves
# like the backend run it replaces. Overridable by env for live tuning (the
# operational note: raise the round timeout to 90-150s for real cold-spawns).
_DEFAULT_ROUND_TIMEOUT_S = 90.0
_DEFAULT_MAX_STEPS = 20


def _norm(handle: str) -> str:
    return (handle or "").strip().lstrip("@").lower()


# ── Roster (local mirror, no HTTP) ───────────────────────────────────────────


def list_participants(room: str, engine_handle: str) -> list[str]:
    """The room's negotiable participants: registered agents minus every engine.

    Read from the local mirror (``agents/<handle>``) — the same source
    ``connector_targets`` uses — so no network call is needed. Excludes the
    summoned engine itself and any *other* engine (an engine never negotiates
    another engine), mirroring the backend's ``_NON_PARTICIPANTS`` filter.
    """
    me = _norm(engine_handle)
    participants: list[str] = []
    for handle in list_agent_handles(room):
        if _norm(handle) == me:
            continue
        manifest = load_manifest(room, handle)
        if manifest is None or manifest.adapter == "engine":
            continue
        participants.append(handle)
    return participants


# ── Openings (backend /messages API — the host holds no transcript) ──────────


async def fetch_openings(api_url: str, room: str, participants: list[str]) -> dict[str, str]:
    """Each participant's latest opening prose from the backend transcript.

    The issue-discovery seed. The backend returns messages newest-first, so the
    first non-empty message we see per participant is their most recent position.
    A silent agent gets a bare stub so discovery still sees the full roster
    (mirrors the backend aligner's ``_opening_positions``). Best-effort: a fetch
    failure yields all-stubs rather than sinking the negotiation.
    """
    wanted = {_norm(p): p for p in participants}
    latest: dict[str, str] = {}
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(f"{api_url}/api/rooms/{room}/messages", params={"limit": 500})
            resp.raise_for_status()
            messages = resp.json().get("messages", [])
    except Exception as exc:  # noqa: BLE001 - openings are best-effort; stubs still let discovery run
        log.warning("engine: could not fetch openings for room %s: %s", room, exc)
        messages = []

    for msg in messages:  # newest-first
        key = _norm(str(msg.get("sender_handle", "")))
        if key not in wanted or wanted[key] in latest:
            continue
        text = msg.get("content")
        if isinstance(text, str) and text.strip():
            latest[wanted[key]] = text.strip()
    for handle in participants:
        latest.setdefault(handle, f"(no opening position stated by @{handle})")
    return latest


# ── Brain (host LLM config — litellm by default, pi where it lives) ──────────


def build_host_brain(config: MyceliumConfig, episode: str) -> Callable[..., str]:
    """Build the engine's cognitive brain from the **host** LLM config.

    Default ``litellm`` (stateless, over the mycelium-configured model). Set
    ``ALIGNER_BRAIN=pi`` to drive a persistent Pi session instead — now possible
    because the runtime lives on the host, where ``pi`` is installed.
    Session/binary/timeout/sandbox mirror the backend knobs so a
    host run is configured identically to the backend run it replaces.
    """
    model = config.llm.model
    if not model:
        msg = "engine: no llm.model configured — set `mycelium config set llm.model ...`"
        raise ValueError(msg)

    if os.getenv("ALIGNER_BRAIN", "litellm").strip().lower() != "pi":
        from mycelium.engine.mediator import build_litellm_brain

        return build_litellm_brain(model, api_key=config.llm.api_key, base_url=config.llm.base_url)

    from mycelium.engine.brain import PiBrain

    slug = re.sub(r"[^A-Za-z0-9._-]+", "-", episode).strip("-") or "align"
    session_dir = Path(tempfile.gettempdir()) / "mycelium-pi-sessions"
    session_dir.mkdir(parents=True, exist_ok=True)
    return PiBrain(
        session_path=session_dir / f"{slug}.jsonl",
        model=model,
        api_key=config.llm.api_key,
        base_url=config.llm.base_url,
        binary=os.getenv("ALIGNER_PI_BINARY", "pi"),
        timeout_s=float(os.getenv("ALIGNER_PI_TIMEOUT_S", "120")),
        openshell=os.getenv("ALIGNER_PI_OPENSHELL", "false").strip().lower() == "true",
    )


# ── Connector-backed channel ─────────────────────────────────────────────────


class _QueueEngineChannel:
    """An :class:`EngineChannel` over the connector's ``publish`` + a routed queue.

    ``publish`` broadcasts on the connector's own SLIM session (no new
    connection). ``receive`` pops the next inbound content dict the connector's
    receive loop routed here while this drive is active — the agent replies
    addressed to the engine.
    """

    def __init__(
        self, publish: Callable[[dict], Awaitable[None]], queue: asyncio.Queue[dict]
    ) -> None:
        self._publish = publish
        self._queue = queue

    async def publish(self, content: dict[str, Any]) -> None:
        await self._publish(content)

    async def receive(self, *, timeout_s: float) -> dict[str, Any] | None:
        try:
            return await asyncio.wait_for(self._queue.get(), timeout_s)
        except TimeoutError:
            return None


# ── The dispatch entry the connector calls ───────────────────────────────────


async def dispatch_engine(
    *,
    config: MyceliumConfig,
    state: DaemonState,
    room: str,
    handle: str,
    kind: str | None,
    publish: Callable[[dict], Awaitable[None]],
) -> None:
    """Run one host-side negotiation as engine ``@handle`` over its connector.

    Registers a drive-active queue (also the re-summon guard: a second summon
    while a drive is in flight is ignored), sources roster + openings + brain,
    drives NEGMAS to a verdict over the connector's session, then deregisters.
    Never raises — the connector's ``_guarded_inbound`` wrapper logs, but a drive
    failure must always release the queue so the engine can be summoned again.
    """
    from mycelium.engine.runtime import _episode_urn, drive_over_channel

    if handle in state.active_drives:
        log.info("engine @%s already driving in %s; ignoring re-summon", handle, room)
        return

    queue: asyncio.Queue[dict] = asyncio.Queue()
    state.active_drives[handle] = queue
    try:
        participants = list_participants(room, handle)
        if not participants:
            log.warning("engine @%s summoned in %s but no participants to negotiate", handle, room)
            return
        openings = await fetch_openings(config.server.api_url, room, participants)
        brain = build_host_brain(config, _episode_urn(room))
        channel = _QueueEngineChannel(publish, queue)
        log.info(
            "engine @%s driving %s over host runtime (%d participants)",
            handle,
            room,
            len(participants),
        )
        await drive_over_channel(
            handle=handle,
            room=room,
            kind=kind or "aligner",
            participants=participants,
            openings=openings,
            brain=brain,
            channel=channel,
            max_steps=int(os.getenv("ALIGNER_MEDIATOR_MAX_STEPS", str(_DEFAULT_MAX_STEPS))),
            round_timeout_s=float(
                os.getenv("ALIGNER_ROUND_TIMEOUT_S", str(_DEFAULT_ROUND_TIMEOUT_S))
            ),
        )
    finally:
        state.active_drives.pop(handle, None)
