# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""Lean L9 envelope helpers for the daemon connector (stdlib only).

The connector only needs to do two L9 things, so this is a small, dependency-free
counterpart to ``fastapi-backend/app/services/l9.py`` rather than a copy of its
pydantic model tree:

1. **Read** an inbound message: pull the sender, recipients, message id, kind,
   and the human-facing text a spawned turn should see.
2. **Build a reply**: an ``exchange`` envelope parented on the message that woke
   the agent, wrapped in a content dict under the additive ``l9`` key.

The reply is emitted in the **exact shape** the backend's
``l9.envelope_to_dict(l9.build_envelope(kind=exchange, ...))`` produces, so the
backend persister's ``l9.parse_envelope`` (pydantic-validating) accepts it
unchanged. Keep this shape in sync with the backend if the L9 binding version
moves; the source of truth for the shape is ``app.services.l9`` /
``app.services.l9_models``.
"""

from __future__ import annotations

import json
import uuid
from typing import Any

# Mirror the backend envelope constants (``app.services.l9``). The version
# tracks the vendored ioc-protocols-models binding.
PROTOCOL = "SSTP"
SUBPROTOCOL = "mycelium"
VERSION = "0.0.6"

# The additive key an L9 envelope rides under inside a message's content JSON.
CONTENT_L9_KEY = "l9"

# The content field carrying the human-facing message body (matches the HTTP
# ``MessageCreate.content`` semantics). A connector reads it to prompt the turn
# and writes it on the reply.
CONTENT_TEXT_KEY = "content"

# ``exchange`` is the kind for room turns (ticks/replies/human messages). The
# connector only wakes on and only emits this kind; system envelopes
# (``commit``/``knowledge``) are observed but never trigger a spawn.
EXCHANGE_KIND = "exchange"

# ``knowledge`` is the memory-sync kind: a ``knowledge`` message
# carries markdown content the connector writes into its local store + reindexes
# (push-with-content). It never wakes a turn; it updates the working set.
KNOWLEDGE_KIND = "knowledge"


class L9ValidationError(ValueError):
    """A hand-crafted envelope's kind/subkind falls outside the wire vocabulary."""


# Kind -> allowed subkinds. Mirrors the backend's authoritative table
# (``app.services.l9.VALID_SUBKINDS``) byte-for-byte; see
# ``contracts/slim-l9-wire.json`` for the drift guard both suites assert
# against. An empty/None subkind is always valid, whatever the kind.
VALID_SUBKINDS: dict[str, frozenset[str]] = {
    "knowledge": frozenset({"query", "distillation", "extraction", "feedback"}),
    "commit": frozenset({"converged", "resolved", "rejected"}),
    "intent": frozenset({"coordinator-assignment", "mission"}),
    "exchange": frozenset({"team-formation"}),
    "contingency": frozenset({"negotiation"}),
}

VALID_KINDS: frozenset[str] = frozenset(VALID_SUBKINDS)


def validate_kind(kind: str) -> None:
    """Reject a kind outside the L9 vocabulary."""
    if kind not in VALID_KINDS:
        raise L9ValidationError(f"invalid kind {kind!r} (allowed: {sorted(VALID_KINDS)})")


def validate_subkind(kind: str, subkind: str | None) -> None:
    """Reject a subkind outside the allowed table for ``kind`` (mirrors the backend)."""
    if not subkind:
        return
    allowed = VALID_SUBKINDS.get(kind, frozenset())
    if subkind not in allowed:
        raise L9ValidationError(
            f"invalid subkind {subkind!r} for kind={kind} (allowed: {sorted(allowed)})"
        )


def room_episode(room: str) -> str:
    """The room's live-episode URN; must match the backend's ``l9.episode_urn``."""
    return f"urn:ioc:mycelium:episode:{room}:live"


def room_topic(room: str) -> str:
    """The room's topic URN; must match the backend's ``l9.topic_urn``."""
    return f"urn:concept:mycelium:{room}"


def build_envelope_content(
    *,
    kind: str,
    subkind: str | None = None,
    sender: str,
    recipients: list[str] | None = None,
    episode: str,
    parents: list[str] | None = None,
    topic: str | None = None,
    text: str = "",
    message_id: str | None = None,
    payload_type: str = "data",
    payload_data: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a full content dict for a hand-crafted envelope of any kind/subkind.

    The general form: :func:`build_reply_content` is the ``exchange``-reply
    specialization every connector uses; this is the escape hatch for crafting
    anything else (a ``commit``, a ``knowledge`` push, an odd subkind): the CLI's
    ``mycelium l9 send`` plumbing. Raises :class:`L9ValidationError` before
    touching the wire if ``subkind`` isn't valid for ``kind``.
    """
    validate_subkind(kind, subkind)

    actors: list[dict[str, str]] = [{"id": sender, "role": "agent"}]
    actors += [{"id": r, "role": "agent"} for r in (recipients or [])]

    header: dict[str, Any] = {
        "protocol": PROTOCOL,
        "subprotocol": SUBPROTOCOL,
        "version": VERSION,
        "kind": kind,
    }
    if subkind:
        header["subkind"] = subkind
    # ``participants.groups`` is required-but-nullable in the schema; the
    # backend restores an explicit null after ``exclude_none``, so we mirror
    # that here for a clean re-validation.
    header["participants"] = {"actors": actors, "groups": None}
    header["message"] = {
        "id": message_id or str(uuid.uuid4()),
        "parents": list(parents or []),
        "episode": episode,
    }
    if topic:
        header["context"] = {"topic": topic}

    envelope: dict[str, Any] = {
        "header": header,
        "payload": {"type": payload_type, "data": payload_data or {}},
    }
    return {CONTENT_TEXT_KEY: text, CONTENT_L9_KEY: envelope}


def build_reply_content(
    *,
    sender: str,
    recipients: list[str],
    episode: str,
    parents: list[str],
    topic: str | None = None,
    text: str = "",
    message_id: str | None = None,
    payload_type: str = "reply",
    payload_data: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a full content dict for an agent reply: ``{content, l9: <envelope>}``.

    The envelope is an ``exchange`` (no subkind, always valid), with ``sender``
    as the first actor and ``recipients`` after it, parented on ``parents`` (the
    message that woke the agent) so the backend's causal ordering + transcript
    stay correct.
    """
    return build_envelope_content(
        kind=EXCHANGE_KIND,
        sender=sender,
        recipients=recipients,
        episode=episode,
        parents=parents,
        topic=topic,
        text=text,
        message_id=message_id,
        payload_type=payload_type,
        payload_data=payload_data,
    )


def serialize(content: dict[str, Any]) -> bytes:
    """Encode a content dict to publishable bytes."""
    return json.dumps(content).encode("utf-8")


def parse(data: bytes) -> dict[str, Any] | None:
    """Decode inbound bytes to a content dict, or ``None`` if not a JSON object."""
    try:
        decoded = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None
    return decoded if isinstance(decoded, dict) else None


def envelope_of(content: dict[str, Any]) -> dict[str, Any] | None:
    """The ``l9`` envelope embedded in a content dict, if any."""
    env = content.get(CONTENT_L9_KEY)
    return env if isinstance(env, dict) else None


def _actors(content: dict[str, Any]) -> list[dict[str, Any]]:
    env = envelope_of(content) or {}
    participants = env.get("header", {}).get("participants", {})
    actors = participants.get("actors")
    return [a for a in actors if isinstance(a, dict)] if isinstance(actors, list) else []


def sender_of(content: dict[str, Any]) -> str | None:
    """The sending handle (first actor), by convention."""
    actors = _actors(content)
    if not actors:
        return None
    sender = actors[0].get("id")
    return sender if isinstance(sender, str) else None


def recipients_of(content: dict[str, Any]) -> list[str]:
    """The recipient handles (every actor after the sender)."""
    return [a["id"] for a in _actors(content)[1:] if isinstance(a.get("id"), str)]


def message_id_of(content: dict[str, Any]) -> str | None:
    """The L9 message id (used to parent a reply)."""
    env = envelope_of(content) or {}
    mid = env.get("header", {}).get("message", {}).get("id")
    return mid if isinstance(mid, str) else None


def episode_of(content: dict[str, Any]) -> str | None:
    env = envelope_of(content) or {}
    ep = env.get("header", {}).get("message", {}).get("episode")
    return ep if isinstance(ep, str) else None


def topic_of(content: dict[str, Any]) -> str | None:
    env = envelope_of(content) or {}
    topic = env.get("header", {}).get("context", {}).get("topic")
    return topic if isinstance(topic, str) else None


def kind_of(content: dict[str, Any]) -> str | None:
    env = envelope_of(content) or {}
    kind = env.get("header", {}).get("kind")
    return kind if isinstance(kind, str) else None


def payload_data_of(content: dict[str, Any]) -> dict[str, Any]:
    """The L9 payload ``data`` dict of a message (empty when absent).

    Used to read a ``knowledge`` message's carried memory write (key + markdown
    content + version) so the connector can apply it locally.
    """
    env = envelope_of(content) or {}
    data = env.get("payload", {}).get("data")
    return data if isinstance(data, dict) else {}


def payload_type_of(content: dict[str, Any]) -> str | None:
    """The L9 payload ``type`` of a message (e.g. ``message``/``reply``/``keepalive``)."""
    env = envelope_of(content) or {}
    ptype = env.get("payload", {}).get("type")
    return ptype if isinstance(ptype, str) else None


def _iter_text(value: Any) -> list[str]:
    """Every string leaf in a nested value (mirrors the persister's scan)."""
    out: list[str] = []
    if isinstance(value, str):
        out.append(value)
    elif isinstance(value, dict):
        for v in value.values():
            out.extend(_iter_text(v))
    elif isinstance(value, list):
        for v in value:
            out.extend(_iter_text(v))
    return out


def human_text_of(content: dict[str, Any]) -> str:
    """The human-facing body a spawned turn should read.

    Prefers the canonical ``content`` field; otherwise joins every string leaf
    outside the ``l9`` envelope (so a message that carried its text elsewhere
    still reaches the agent).
    """
    text = content.get(CONTENT_TEXT_KEY)
    if isinstance(text, str) and text.strip():
        return text
    parts: list[str] = []
    for key, value in content.items():
        if key == CONTENT_L9_KEY:
            continue
        parts.extend(t for t in _iter_text(value) if t.strip())
    return "\n".join(parts)
