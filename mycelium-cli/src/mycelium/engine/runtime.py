# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""The host-side SAO mediation drive loop.

Drives NEGMAS over SLIM as the summoned engine handle: discover issues from the
opening prose, ``@``-address one agent per turn, read the real reply, interpret
it, step NEGMAS, and emit a ``commit:converged`` when the mechanism reaches
agreement: the same seam the backend's ``task_sync`` consumes off the channel.

**The channel is an injected seam** (:class:`EngineChannel`) so the drive *logic*
is unit-testable with a fake. The real SLIM transport
(:class:`SlimEngineChannel`) is the one part that needs a live node to validate.
Keep the two apart.
"""

from __future__ import annotations

import asyncio
import logging
import re
import uuid
from typing import TYPE_CHECKING, Any, Protocol

from mycelium.engine import mediator

if TYPE_CHECKING:
    from collections.abc import Callable

logger = logging.getLogger(__name__)

# Same fix as the backend: neutralize ``@`` in outgoing prompts so the broker's
# summary (which names the other agents) doesn't spuriously wake them; only the
# L9 recipient should wake, one agent per turn.
_AT_MENTION = re.compile(r"@(?=\w)")


class EngineChannel(Protocol):
    """The SLIM seam the drive loop needs: publish a content dict, receive one.

    ``publish`` broadcasts one L9 content dict onto the room channel. ``receive``
    returns the next inbound content dict (already parsed) or ``None`` on timeout.
    A real implementation wraps the CLI ``SlimClient``; tests inject a fake.
    """

    async def publish(self, content: dict[str, Any]) -> None: ...

    async def receive(self, *, timeout_s: float) -> dict[str, Any] | None: ...


def _norm(handle: str) -> str:
    return (handle or "").strip().lstrip("@").lower()


def _episode_urn(room: str) -> str:
    # Matches the backend aligner's ``l9.episode_urn(room, "align")`` form so the
    # persister/plan_sync correlate the engine's turns + verdict to one episode.
    return f"urn:ioc:mycelium:episode:{room}:align"


def _topic_urn(room: str) -> str:
    return f"urn:concept:mycelium:{room}"


class NegotiationRunner:
    """Runs one SAO negotiation as ``engine_handle`` over an :class:`EngineChannel`."""

    def __init__(
        self,
        *,
        engine_handle: str,
        room: str,
        episode: str,
        topic: str,
        channel: EngineChannel,
        llm_session: Callable[..., str],
        max_steps: int = 20,
        round_timeout_s: float = 90.0,
    ) -> None:
        self._handle = engine_handle
        self._room = room
        self._episode = episode
        self._topic = topic
        self._channel = channel
        self._llm_session = llm_session
        self._max_steps = max_steps
        self._round_timeout_s = round_timeout_s

    async def run(self, participants: list[str], openings: dict[str, str]) -> dict[str, str] | None:
        """Discover → drive NEGMAS → emit the verdict. Returns the agreed map or None.

        ``participants`` are the room members to negotiate (the engine handle is
        already excluded by the caller). ``openings`` maps each to its latest
        opening prose (used only for issue discovery).
        """
        from mycelium.slim import l9

        issues = await asyncio.to_thread(
            mediator.discover_issues,
            "Converge on the room's open question; agree one value per issue.",
            openings,
            llm=self._llm_session,
        )
        if not issues:
            logger.info("engine %s: no issues discovered; rejecting", self._handle)
            await self._emit_verdict(l9, {}, converged=False)
            return None

        loop = asyncio.get_running_loop()
        negotiation = mediator.MediatedNegotiation(
            issues=issues,
            cap=self._max_steps,
            loop=loop,
            fetch_prose=self._slim_turn,
            turn_timeout_s=self._round_timeout_s,
            llm=self._llm_session,
        )
        mech = mediator.build_mechanism(issues, participants, negotiation, cap=self._max_steps)
        await asyncio.to_thread(mech.run)

        assignments = mediator.agreement_assignments(mech, negotiation.names)
        converged = assignments is not None
        logger.info(
            "engine %s room %s → %s in %d steps (%s)",
            self._handle,
            self._room,
            "agreement" if converged else "no agreement",
            mech.current_step,
            assignments,
        )
        await self._emit_verdict(l9, assignments or {}, converged=converged)
        return assignments

    async def _slim_turn(self, handle: str, prompt: str, round_n: int) -> str:
        """Publish one ``@handle`` prompt as the engine; await that handle's reply.

        Bounded by ``round_timeout_s`` (a silent agent yields ``""``, read as a
        reject downstream) so the mechanism can never hang. Runs in the NEGMAS
        worker thread; the publish/receive is bridged to this loop by
        ``MediatedNegotiation``.
        """
        from mycelium.slim import l9

        safe_prompt = _AT_MENTION.sub("", prompt)
        content = l9.build_reply_content(
            sender=self._handle,
            recipients=[handle],
            episode=self._episode,
            parents=[],
            topic=self._topic,
            text=safe_prompt,
            message_id=str(uuid.uuid4()),
            payload_type="tick",
            payload_data={"round": round_n, "action": "position"},
        )
        try:
            await self._channel.publish(content)
        except Exception:
            logger.warning(
                "engine %s failed to prompt @%s (step %d)", self._handle, handle, round_n
            )
            return ""

        loop = asyncio.get_running_loop()
        deadline = loop.time() + self._round_timeout_s
        pending = _norm(handle)
        while loop.time() < deadline:
            inbound = await self._channel.receive(timeout_s=max(0.1, deadline - loop.time()))
            if inbound is None:
                continue
            if l9.payload_type_of(inbound) == "keepalive":
                continue  # an idle keepalive ping, never a negotiation reply
            sender = l9.sender_of(inbound)
            if sender is None or _norm(sender) != pending:
                continue  # not the addressed agent's reply; ignore (own prompt, others)
            if (l9.payload_data_of(inbound) or {}).get("action") == "position":
                continue  # a prompt echo, not a reply
            return l9.human_text_of(inbound) or ""
        return ""

    async def _emit_verdict(self, l9: Any, assignments: dict[str, str], *, converged: bool) -> None:  # noqa: ANN401
        """Publish the ``commit:converged``/``rejected`` as the engine, onto the channel.

        The backend's persister sees this and fires ``task_sync`` → task compile
        → memory sync (unchanged tail), so the host engine only has to emit it.
        """
        summary = (
            "✓ agreement: " + " · ".join(f"{k} = {v}" for k, v in assignments.items())
            if converged
            else "✗ not converged"
        )
        content = l9.build_reply_content(
            sender=self._handle,
            recipients=[],
            episode=self._episode,
            parents=[],
            topic=self._topic,
            text=summary,
            message_id=str(uuid.uuid4()),
            payload_type="consensus",
            payload_data={"assignments": assignments},
        )
        # Mark the envelope as a commit so the persister's converged detector fires.
        env = content.get("l9")
        if isinstance(env, dict):
            env.setdefault("header", {})["kind"] = "commit"
            env["header"]["subkind"] = "converged" if converged else "rejected"
        try:
            await self._channel.publish(content)
        except Exception:
            logger.warning("engine %s failed to emit verdict on %s", self._handle, self._room)


# ── Live SLIM transport (validated against a running node, not in unit tests) ──


class SlimEngineChannel:
    """An :class:`EngineChannel` backed by a live SLIM session.

    Wraps the CLI ``SlimClient`` (the same transport the daemon connector uses).
    This is the one part of the runtime whose correctness only shows up live (the
    wire format + real agent connectors), so it's deliberately thin: build the
    content dicts in :class:`NegotiationRunner`, move bytes here.
    """

    def __init__(self, client: Any, session: Any) -> None:  # noqa: ANN401 - slim_bindings types
        self._client = client
        self._session = session

    async def publish(self, content: dict[str, Any]) -> None:
        from mycelium.slim import l9
        from mycelium.slim.client import SlimClient

        await SlimClient.publish(self._session, l9.serialize(content))

    async def receive(self, *, timeout_s: float) -> dict[str, Any] | None:
        from mycelium.slim import l9
        from mycelium.slim.client import SlimClient, SlimReceiveTimeout

        try:
            message = await SlimClient.receive_message(self._session, timeout_s=timeout_s)
        except SlimReceiveTimeout:
            return None
        return l9.parse(message.payload)


async def run_negotiation_over_channel(
    *,
    handle: str,
    room: str,
    kind: str,
    participants: list[str],
    openings: dict[str, str],
    llm_session: Callable[..., str],
    channel: EngineChannel,
    max_steps: int = 20,
    round_timeout_s: float = 90.0,
) -> dict[str, str] | None:
    """Run one negotiation as ``@handle`` over an already-open :class:`EngineChannel`.

    The single drive entry point, transport-agnostic: the caller owns the channel
    (a :class:`SlimEngineChannel` on the engine's own session, or a connector-
    backed queue channel). ``kind`` is
    accepted for forward-compat (future CEs route here); only ``aligner`` runs a
    NEGMAS SAO today.
    """
    drive = NegotiationRunner(
        engine_handle=handle,
        room=room,
        episode=_episode_urn(room),
        topic=_topic_urn(room),
        channel=channel,
        llm_session=llm_session,
        max_steps=max_steps,
        round_timeout_s=round_timeout_s,
    )
    return await drive.run(participants, openings)
