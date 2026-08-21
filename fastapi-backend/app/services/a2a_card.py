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

import asyncio
import ipaddress
import logging
import socket
from dataclasses import dataclass, field
from urllib.parse import urlparse

import httpx
from a2a.client import A2ACardResolver
from a2a.client.errors import A2AClientError
from a2a.types import AgentCard

from app.config import settings

logger = logging.getLogger(__name__)

NEW_CARD_PATH = "/.well-known/agent-card.json"
OLD_CARD_PATH = "/.well-known/agent.json"
CARD_PATHS = (NEW_CARD_PATH, OLD_CARD_PATH)

_RESOLVE_TIMEOUT_S = 20.0


class A2aCardError(Exception):
    """The remote agent's card could not be resolved or is unusable."""


async def _guard_public_host(base: str) -> None:
    """Refuse a card host that resolves to a non-public address (SSRF guard).

    Registering or summoning an a2a agent makes the backend dial the card's
    host, so a caller-supplied ``http://169.254.169.254/...`` or an internal
    address would otherwise let an (unauthenticated, under the default gate-off)
    user reach the backend's own network. We resolve the host and reject any
    non-global IP. Best-effort against DNS rebinding: httpx re-resolves at
    connect time, so this narrows the window rather than closing it fully.
    """
    if settings.A2A_ALLOW_PRIVATE_HOSTS:
        return
    host = urlparse(base).hostname
    if not host:
        raise A2aCardError(f"card URL has no host: {base!r}")
    try:
        infos = await asyncio.get_running_loop().getaddrinfo(host, None)
    except socket.gaierror as exc:
        raise A2aCardError(f"card host {host!r} did not resolve: {exc}") from exc
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if not ip.is_global:
            raise A2aCardError(
                f"card host {host!r} resolves to a non-public address {ip} (SSRF guard); "
                "set A2A_ALLOW_PRIVATE_HOSTS=1 only for a trusted internal deployment"
            )


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
    raw, path = await resolve_raw_card(base_url, http=http)
    return _project(raw, base=base_url.strip().rstrip("/"), card_path=path)


async def resolve_raw_card(
    base_url: str,
    *,
    http: httpx.AsyncClient | None = None,
) -> tuple[AgentCard, str]:
    """Resolve the raw proto ``AgentCard`` + the well-known path that served it.

    The dual-path probe shared by registration (which projects the card) and the
    seat driver (which needs the raw card to build a send client). Raises
    :class:`A2aCardError` if neither path resolves.
    """
    base = base_url.strip().rstrip("/")
    if not base.startswith(("http://", "https://")):
        raise A2aCardError(f"card URL must be http(s): {base_url!r}")
    await _guard_public_host(base)

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
            return card, path
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
