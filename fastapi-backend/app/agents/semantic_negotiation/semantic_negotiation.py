"""Semantic negotiation pipeline — top-level orchestrator.

Wires together the three components in order:

1. :class:`~.intent_discovery.IntentDiscovery`
   Returns the list of negotiable issues.

2. :class:`~.options_generation.OptionsGeneration`
   Returns candidate options per issue.

3. :class:`~.negotiation_model.NegotiationModel`
   Runs a NegMAS SAO negotiation via RoomNegotiator (room-message handshake).
"""
from __future__ import annotations

import asyncio
from typing import Any, Callable, Dict, List, Optional

from .intent_discovery import IntentDiscovery
from .negotiation_model import (
    NegotiationModel,
    NegotiationOutcome,
    NegotiationParticipant,
    NegotiationResult,
)
from .options_generation import OptionsGeneration

__all__ = [
    "SemanticNegotiationPipeline",
    "NegotiationModel",
    "NegotiationParticipant",
    "NegotiationOutcome",
    "NegotiationResult",
    "IntentDiscovery",
    "OptionsGeneration",
]


class SemanticNegotiationPipeline:
    """Orchestrates the full three-component semantic negotiation flow.

    Usage::

        pipeline = SemanticNegotiationPipeline(
            participants=[
                NegotiationParticipant(id="agent-a", name="Agent A"),
                NegotiationParticipant(id="agent-b", name="Agent B"),
            ],
            room_name="room-abc",
            loop=asyncio.get_event_loop(),
            post_message_coro=coordination._post_message,
        )
        result = pipeline.run(content_text="Plan a 2-week sprint")

    Args:
        context: Shared interaction context forwarded to components 1 and 2.
        agents: Agent descriptors forwarded to component 2.
        memories: Per-agent memory objects forwarded to component 2.
        participants: Negotiation participants for component 3.
        n_steps: Maximum SAO rounds for the negotiation.
        room_name: Mycelium room to route messages through.
        loop: The asyncio event loop for the room bridge.
        post_message_coro: Async callable for posting room messages.
        reply_timeout: Per-round reply timeout for RoomNegotiator.
    """

    def __init__(
        self,
        context: Any = None,
        agents: Optional[List[Any]] = None,
        memories: Optional[Dict[str, Any]] = None,
        participants: Optional[List[NegotiationParticipant]] = None,
        n_steps: int = 100,
        room_name: str = "unknown",
        loop: Optional[asyncio.AbstractEventLoop] = None,
        post_message_coro: Optional[Callable] = None,
        reply_timeout: float = 60.0,
    ) -> None:
        self.context = context
        self.agents = agents or []
        self.memories = memories or {}
        self.participants = participants or []
        self.n_steps = n_steps
        self.room_name = room_name
        self.loop = loop
        self.post_message_coro = post_message_coro
        self.reply_timeout = reply_timeout

        self._intent_discovery = IntentDiscovery(context=self.context)
        self._options_generation = OptionsGeneration(
            context=self.context,
            agents=self.agents,
            memories=self.memories,
        )
        self._negotiation_model = NegotiationModel(n_steps=self.n_steps, strategy=None)

        # Populated by NegotiationModel.run() *before* mechanism.run() blocks,
        # so coordination.on_agent_response() can route replies during negotiation.
        self.negotiator_registry: dict = {}

    def run(
        self,
        content_text: Optional[str] = None,
        issues: Optional[List[str]] = None,
        options_per_issue: Optional[Dict[str, List[str]]] = None,
        participants: Optional[List[NegotiationParticipant]] = None,
    ) -> NegotiationResult:
        """Execute the full pipeline end-to-end.

        Components 1 and 2 are only invoked when their outputs are not
        pre-supplied by the caller.

        Args:
            content_text: Natural-language mission description for component 1.
                Ignored when *issues* is provided.
            issues: Pre-supplied ordered list of issue identifiers.
            options_per_issue: Pre-supplied ``{issue_id: [option, ...]}`` mapping.
            participants: Override self.participants for component 3.

        Returns:
            A :class:`~.negotiation_model.NegotiationResult`.
        """
        resolved_participants = participants if participants is not None else self.participants

        if issues is None:
            issues = self._intent_discovery.discover(content_text=content_text)

        if options_per_issue is None:
            options_per_issue = self._options_generation.generate(issues)

        result = self._negotiation_model.run(
            issues=issues,
            options_per_issue=options_per_issue,
            participants=resolved_participants,
            room_name=self.room_name,
            loop=self.loop,
            post_message_coro=self.post_message_coro,
            reply_timeout=self.reply_timeout,
            registry=self.negotiator_registry,
        )

        return result
