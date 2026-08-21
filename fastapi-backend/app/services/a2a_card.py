# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""Resolve and validate an external agent's A2A Agent Card.

The client leg of the A2A bridge (epic #719). Given a base URL, fetch the
remote agent's Agent Card and project the handful of fields the room needs to
register it as a member: display name, advertised skills, and the endpoint the
seat driver (#714) will call.

Two drift facts, proven by the #712 spike against a live agent, are baked in:

- **Dual-path probe.** The current spec serves the card at
  ``/.well-known/agent-card.json``; deployed agents still serve the older
  ``/.well-known/agent.json``. We try the new path first, then the old.
- The send-time quirk (older servers require ``configuration.acceptedOutputModes``)
  lives with the seat driver, not here — resolution is a plain card GET.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

import httpx
from a2a.client import A2ACardResolver
from a2a.client.errors import A2AClientError

logger = logging.getLogger(__name__)

NEW_CARD_PATH = "/.well-known/agent-card.json"
OLD_CARD_PATH = "/.well-known/agent.json"
CARD_PATHS = (NEW_CARD_PATH, OLD_CARD_PATH)

_RESOLVE_TIMEOUT_S = 20.0


class A2aCardError(Exception):
    """The remote agent's card could not be resolved or is unusable."""


@dataclass(frozen=True)
class ResolvedSkill:
    id: str
    name: str
    description: str = ""


@dataclass(frozen=True)
class ResolvedCard:
    """The bridge-relevant projection of a remote Agent Card."""

    name: str
    version: str
    endpoint: str
    protocol_binding: str
    card_path: str
    streaming: bool
    description: str = ""
    skills: list[ResolvedSkill] = field(default_factory=list)

    @property
    def skill_ids(self) -> list[str]:
        return [s.id for s in self.skills]


async def resolve_card(
    base_url: str,
    *,
    http: httpx.AsyncClient | None = None,
) -> ResolvedCard:
    """Fetch and project the Agent Card served under ``base_url``.

    Tries the new well-known path then the old one. Raises
    :class:`A2aCardError` with a human-readable reason if neither resolves.
    """
    base = base_url.strip().rstrip("/")
    if not base.startswith(("http://", "https://")):
        raise A2aCardError(f"card URL must be http(s): {base_url!r}")

    owns_client = http is None
    client = http or httpx.AsyncClient(timeout=_RESOLVE_TIMEOUT_S)
    try:
        last_error: Exception | None = None
        for path in CARD_PATHS:
            try:
                card = await A2ACardResolver(client, base, agent_card_path=path).get_agent_card()
            except (A2AClientError, httpx.HTTPError, ValueError) as exc:
                last_error = exc
                logger.debug("a2a card probe %s%s failed: %r", base, path, exc)
                continue
            return _project(card, base=base, card_path=path)
        raise A2aCardError(
            f"no Agent Card at {base}{NEW_CARD_PATH} or {OLD_CARD_PATH}: {last_error}"
        )
    finally:
        if owns_client:
            await client.aclose()


def _pick_interface(card: object, base: str) -> tuple[str, str]:
    """Endpoint URL + protocol binding, preferring a JSON-RPC interface.

    The proto card carries the endpoint in ``supported_interfaces`` (each an
    url + ``protocol_binding``), not a top-level ``url``. JSON-RPC is the
    transport the seat driver speaks, so prefer it; fall back to the first
    interface, then to the card's base URL.
    """
    interfaces = list(getattr(card, "supported_interfaces", []) or [])
    for iface in interfaces:
        if (getattr(iface, "protocol_binding", "") or "").upper() == "JSONRPC" and iface.url:
            return iface.url, "JSONRPC"
    if interfaces and interfaces[0].url:
        return interfaces[0].url, getattr(interfaces[0], "protocol_binding", "") or ""
    return base, ""


def _project(card: object, *, base: str, card_path: str) -> ResolvedCard:
    name = getattr(card, "name", "") or ""
    if not name:
        raise A2aCardError("Agent Card has no name")
    endpoint, binding = _pick_interface(card, base)
    skills = [
        ResolvedSkill(
            id=s.id,
            name=getattr(s, "name", "") or s.id,
            description=getattr(s, "description", "") or "",
        )
        for s in getattr(card, "skills", []) or []
        if getattr(s, "id", "")
    ]
    caps = getattr(card, "capabilities", None)
    return ResolvedCard(
        name=name,
        version=getattr(card, "version", "") or "",
        endpoint=endpoint,
        protocol_binding=binding,
        card_path=card_path,
        streaming=bool(getattr(caps, "streaming", False)),
        description=getattr(card, "description", "") or "",
        skills=skills,
    )
