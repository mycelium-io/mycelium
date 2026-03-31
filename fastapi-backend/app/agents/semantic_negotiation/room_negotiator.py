# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Julia Valenti

"""RoomNegotiator — NegMAS SAO negotiator that routes decisions through Mycelium rooms.

Routes decisions through room messages rather than HTTP callbacks.
Instead of POSTing to an agent's callback URL, this negotiator:

1. Serialises the current SAO round into an SSTPNegotiateMessage and posts it
   as a ``coordination_tick`` room message.
2. Blocks the NegMAS thread (via asyncio.Future + run_coroutine_threadsafe) waiting
   for the agent to reply in the room.
3. ``on_agent_reply()`` is called by the coordination layer when the agent's response
   arrives (same path as on_agent_response in coordination.py).

Wire format
-----------
**Server → Agent** (coordination_tick content is a serialised SSTPNegotiateMessage):

The ``payload`` field within the SSTP envelope carries the negotiation action:

    {
      "kind": "negotiate",              # SSTP kind
      ...                               # SSTP envelope fields
      "semantic_context": {
        "session_id": "<room_name>",
        "issues": ["budget", ...],
        "options_per_issue": {...},
        "sao_state": {...} | null,
      },
      "payload": {
        "action": "propose" | "respond",
        "participant_id": "<agent_handle>",
        "round": 4,
        "current_offer": {"budget": "medium", ...} | null,  # respond only
        "proposer_id": "<handle>",                          # respond only
        "history": [...],
        "n_steps": 100
      }
    }

**Agent → Server** (plain JSON content of a room message — unchanged):

    // reply to propose
    { "offer": { "budget": "low", "timeline": "short" } }

    // reply to respond
    { "action": "accept" }   // or "reject" or "end"

On timeout or missing keys, propose returns None (NegMAS skips the turn) and
respond returns ResponseType.REJECT_OFFER.
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import hashlib
import json
import logging
import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from negmas.gb.common import ResponseType
from negmas.sao import SAONegotiator

if TYPE_CHECKING:
    from negmas.sao.common import SAOState

logger = logging.getLogger(__name__)

# Type alias for NegMAS outcomes
Outcome = dict[str, Any] | tuple | None


class RoomNegotiator(SAONegotiator):
    """A NegMAS SAO negotiator that routes every propose/respond decision
    through an Mycelium room message rather than an HTTP callback.

    Args:
        name: Participant display name (passed to NegMAS).
        participant_id: Stable handle of the agent this negotiator represents
            (matches Session.agent_handle in the DB).
        room_name: The room to post coordination ticks into.
        loop: The asyncio event loop running the coordination service.
        post_message_coro: Async callable ``(room_name, message_type, content) → None``
            that inserts the message and fires NOTIFY — typically
            ``coordination._post_message``.
        reply_timeout: Seconds to wait for the agent to reply before
            falling back to the safe default.
    """

    def __init__(
        self,
        name: str,
        participant_id: str,
        room_name: str,
        loop: asyncio.AbstractEventLoop,
        post_message_coro: Any,
        reply_timeout: float = 30.0,
    ) -> None:
        super().__init__(name=name)
        self._participant_id = participant_id
        self._room_name = room_name
        self._loop = loop
        self._post_message_coro = post_message_coro
        self._reply_timeout = reply_timeout
        # Pending future keyed by participant_id; resolved by on_agent_reply()
        self._pending: asyncio.Future[dict] | None = None

    # ------------------------------------------------------------------
    # Called by the coordination layer when the agent posts a reply
    # ------------------------------------------------------------------

    def on_agent_reply(self, content: str) -> None:
        """Resolve the pending future with the agent's JSON reply.

        Called by ``coordination.on_agent_response()`` when the agent whose
        handle matches ``participant_id`` posts a message in the room while
        a negotiation round is in flight.

        Args:
            content: Raw JSON string from the room message's ``content`` field.
        """
        if self._pending is None or self._pending.done():
            return
        try:
            data = json.loads(content)
        except Exception:
            data = {}
        # Schedule the resolution on the event loop (call-safe from any thread)
        self._loop.call_soon_threadsafe(self._pending.set_result, data)

    # ------------------------------------------------------------------
    # NegMAS hooks
    # ------------------------------------------------------------------

    def propose(self, state: SAOState, dest: str | None = None) -> Outcome:
        """Ask the agent (via room message) to propose an offer for this round."""
        issues = self._issue_names()
        payload: dict[str, Any] = {
            "kind": "negotiate",
            "action": "propose",
            "session_id": self._room_name,
            "participant_id": self._participant_id,
            "round": state.step + 1,
            "issue_options": self._issue_options(),
            "history": self._serialise_history(state, issues),
            "n_steps": self._n_steps(),
        }
        reply = self._send_and_wait(payload)
        if reply is None:
            logger.warning(
                "[%s] %s — propose timed out, returning None",
                self._room_name,
                self.name,
            )
            return None

        offer_dict = reply.get("offer")
        if not isinstance(offer_dict, dict):
            logger.warning(
                "[%s] %s — propose reply missing 'offer': %s",
                self._room_name,
                self.name,
                reply,
            )
            return None

        try:
            return self._dict_to_outcome(offer_dict, issues)
        except Exception as exc:
            logger.warning(
                "[%s] %s — propose outcome conversion failed: %s",
                self._room_name,
                self.name,
                exc,
            )
            return None

    def respond(self, state: SAOState, source: str | None = None) -> ResponseType:
        """Ask the agent (via room message) to respond to the current offer."""
        issues = self._issue_names()
        current_offer = (
            self._tuple_to_dict(state.current_offer, issues)
            if state.current_offer is not None
            else None
        )
        payload: dict[str, Any] = {
            "kind": "negotiate",
            "action": "respond",
            "session_id": self._room_name,
            "participant_id": self._participant_id,
            "round": state.step + 1,
            "issue_options": self._issue_options(),
            "current_offer": current_offer,
            "proposer_id": source or "",
            "history": self._serialise_history(state, issues),
            "n_steps": self._n_steps(),
        }
        reply = self._send_and_wait(payload)
        if reply is None:
            logger.warning(
                "[%s] %s — respond timed out, defaulting to reject",
                self._room_name,
                self.name,
            )
            return ResponseType.REJECT_OFFER

        action = reply.get("action", "reject")
        return _parse_response_type(action)

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _send_and_wait(self, payload: dict[str, Any]) -> dict[str, Any] | None:
        """Post the payload as a coordination_tick and block until the agent replies.

        NegMAS runs propose/respond inside asyncio.to_thread, so this method runs
        in a worker thread. We schedule the async post + future creation on the
        event loop via run_coroutine_threadsafe, which returns a
        concurrent.futures.Future we can block on with a timeout.
        """
        conc_future: concurrent.futures.Future[dict] = asyncio.run_coroutine_threadsafe(
            self._post_and_await_reply(payload), self._loop
        )
        try:
            return conc_future.result(timeout=self._reply_timeout)
        except concurrent.futures.TimeoutError:
            logger.warning(
                "[%s] %s — no reply within %.0fs",
                self._room_name,
                self.name,
                self._reply_timeout,
            )
            # Cancel the pending asyncio future so it doesn't linger
            self._loop.call_soon_threadsafe(self._cancel_pending)
            return None
        except Exception:
            logger.exception("[%s] %s — reply wait error", self._room_name, self.name)
            self._loop.call_soon_threadsafe(self._cancel_pending)
            return None

    def _cancel_pending(self) -> None:
        if self._pending is not None and not self._pending.done():
            self._pending.cancel()
        self._pending = None

    async def _post_and_await_reply(self, payload: dict[str, Any]) -> dict:
        """Post the coordination_tick message and await the agent's reply Future.

        Runs on the event loop (called via run_coroutine_threadsafe).
        Wraps the payload in an SSTPNegotiateMessage envelope.
        """
        self._pending = self._loop.create_future()
        content = json.dumps(self._wrap_sstp(payload))
        await self._post_message_coro(
            self._room_name,
            "coordination_tick",
            content,
        )
        # Await with the same timeout so the coroutine completes or raises
        return await asyncio.wait_for(self._pending, timeout=self._reply_timeout)

    def _wrap_sstp(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Wrap the negotiation payload in an SSTPNegotiateMessage envelope.

        Falls back to the bare payload dict if SSTP import fails, so the
        existing wire format is preserved as a safe default.
        """
        try:
            from app.agents.protocol.sstp import SSTPNegotiateMessage

            now = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
            payload_hash = hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()
            msg = SSTPNegotiateMessage.model_validate(
                {
                    "kind": "negotiate",
                    "protocol": "SSTP",
                    "version": "0",
                    "message_id": str(uuid.uuid4()),
                    "dt_created": now,
                    "origin": {
                        "actor_id": "mycelium-backend",
                        "tenant_id": payload.get("session_id", self._room_name),
                    },
                    "semantic_context": {
                        "schema_id": "urn:ioc:schema:negotiate:negmas-sao:v1",
                        "schema_version": "1.0",
                        "session_id": self._room_name,
                        "issues": list(self._issue_names()),
                        "options_per_issue": self._issue_options(),
                    },
                    "payload_hash": payload_hash,
                    "policy_labels": {
                        "sensitivity": "internal",
                        "propagation": "restricted",
                        "retention_policy": "default",
                    },
                    "provenance": {"sources": [], "transforms": []},
                    "payload": payload,
                }
            )
            return msg.model_dump()
        except Exception:
            logger.debug("_wrap_sstp: falling back to bare payload", exc_info=True)
            return payload

    def _issue_names(self) -> list[str]:
        try:
            return [issue.name for issue in self.nmi.outcome_space.issues]
        except Exception:
            return []

    def _issue_options(self) -> dict[str, list[str]]:
        try:
            return {
                issue.name: [str(v) for v in issue.values]
                for issue in self.nmi.outcome_space.issues
            }
        except Exception:
            return {}

    def _n_steps(self) -> int | None:
        try:
            return self.nmi.n_steps
        except Exception:
            return None

    def _tuple_to_dict(
        self, outcome: tuple | dict | None, issues: list[str]
    ) -> dict[str, str] | None:
        if outcome is None:
            return None
        if isinstance(outcome, dict):
            return {k: str(v) for k, v in outcome.items()}
        return {issues[i]: str(v) for i, v in enumerate(outcome)}

    def _dict_to_outcome(self, offer_dict: dict[str, str], issues: list[str]) -> tuple:
        issue_options = self._issue_options()
        result = []
        for issue in issues:
            if issue in offer_dict:
                result.append(offer_dict[issue])
            else:
                # Agent omitted this issue — fall back to first available option
                opts = issue_options.get(issue, [])
                fallback = opts[0] if opts else ""
                logger.warning(
                    "[%s] %s — offer missing issue %r, using fallback %r",
                    self._room_name,
                    self.name,
                    issue,
                    fallback,
                )
                result.append(fallback)
        return tuple(result)

    def _serialise_history(self, state: SAOState, issues: list[str]) -> list[dict]:
        rounds: list[dict] = []
        try:
            for idx, entry in enumerate(state.history or []):
                if hasattr(entry, "offer"):
                    proposer = getattr(entry, "current_proposer", "unknown")
                    offer = entry.offer
                else:
                    proposer, offer = (entry[0], entry[1]) if len(entry) >= 2 else ("unknown", None)
                rounds.append(
                    {
                        "round": idx + 1,
                        "proposer_id": str(proposer),
                        "offer": self._tuple_to_dict(offer, issues) or {},
                    }
                )
        except Exception as exc:
            logger.debug("[%s] history serialisation warning: %s", self._room_name, exc)
        return rounds


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _parse_response_type(action: str) -> ResponseType:
    """Map an agent's string action to a NegMAS ResponseType."""
    action = (action or "").strip().lower()
    if action == "accept":
        return ResponseType.ACCEPT_OFFER
    if action == "end":
        return ResponseType.END_NEGOTIATION
    return ResponseType.REJECT_OFFER
