"""
Dump SSTP JSON Schema(s) or example messages to stdout.

Usage:
    python -m app.agents.protocol.sstp                   # all kinds + union schema
    python -m app.agents.protocol.sstp negotiate         # only the negotiate kind
    python -m app.agents.protocol.sstp intent --indent 4
    python -m app.agents.protocol.sstp all --indent 0    # minified

    python -m app.agents.protocol.sstp --examples        # 3 negotiate examples
    python -m app.agents.protocol.sstp --examples initiate          # initiate only
    python -m app.agents.protocol.sstp --examples offer-accept      # offer-response accept
    python -m app.agents.protocol.sstp --examples offer-reject      # offer-response reject
    python -m app.agents.protocol.sstp --examples all               # all three (default)

Exit code 0 on success; output is valid JSON piped to stdout.

Example:
    python -m app.agents.protocol.sstp negotiate | jq '.properties | keys'
    python -m app.agents.protocol.sstp --examples | jq '.[0].payload'
"""

from __future__ import annotations

import argparse
import hashlib
import json
import uuid

from pydantic import TypeAdapter

from app.agents.protocol.sstp import (
    DelegationMessage,
    EvidenceBundleMessage,
    IntentMessage,
    KnowledgeMessage,
    MemoryDeltaMessage,
    QueryMessage,
    SSTPCommitMessage,
    SSTPNegotiateMessage,
    STPMessage,
    __version__,
)

_KINDS: dict[str, type] = {
    "intent": IntentMessage,
    "delegation": DelegationMessage,
    "knowledge": KnowledgeMessage,
    "query": QueryMessage,
    "commit": SSTPCommitMessage,
    "memory_delta": MemoryDeltaMessage,
    "evidence_bundle": EvidenceBundleMessage,
    "negotiate": SSTPNegotiateMessage,
}

_EXAMPLE_CHOICES = ["initiate", "offer-accept", "offer-reject", "all"]

# ── shared example values ────────────────────────────────────────────────────

_SESSION_ID = "sess-demo-0001"
_TENANT_ID = "ws-demo"
_NOW = "2026-03-04T09:00:00Z"

_EXAMPLE_TRACE = {
    "rounds": [
        {
            "round": 1,
            "proposer_id": "agent-a",
            "offer": {
                "budget": "minimal",
                "timeline": "express",
                "scope": "core",
                "quality": "basic",
            },
        },
        {
            "round": 2,
            "proposer_id": "agent-b",
            "offer": {
                "budget": "uncapped",
                "timeline": "long",
                "scope": "full",
                "quality": "premium",
            },
        },
        {
            "round": 3,
            "proposer_id": "agent-a",
            "offer": {
                "budget": "medium",
                "timeline": "standard",
                "scope": "standard",
                "quality": "standard",
            },
        },
    ],
    "final_agreement": [
        {"issue_id": "budget", "chosen_option": "medium"},
        {"issue_id": "timeline", "chosen_option": "standard"},
        {"issue_id": "scope", "chosen_option": "standard"},
        {"issue_id": "quality", "chosen_option": "standard"},
    ],
    "timedout": False,
    "broken": False,
}


def _hash(payload: dict) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()


def _envelope(actor_id: str, payload: dict) -> dict:
    """Build a minimal but valid SSTPNegotiateMessage dict."""
    return {
        "kind": "negotiate",
        "protocol": "SSTP",
        "version": "0",
        "message_id": str(
            uuid.uuid5(
                uuid.NAMESPACE_URL, f"example:{actor_id}:{json.dumps(payload, sort_keys=True)}"
            )
        ),
        "dt_created": _NOW,
        "origin": {
            "actor_id": actor_id,
            "tenant_id": _TENANT_ID,
        },
        "semantic_context": {
            "schema_id": "urn:ioc:schema:negotiate:negmas-sao:v1",
            "schema_version": "1.0",
            "session_id": _SESSION_ID,
            "sao_state": None,
        },
        "payload_hash": _hash(payload),
        "policy_labels": {
            "sensitivity": "internal",
            "propagation": "restricted",
            "retention_policy": "default",
        },
        "provenance": {"sources": [], "transforms": []},
        "payload": payload,
    }


def _example_initiate() -> dict:
    payload = {
        "content_text": (
            "We need to negotiate a software development contract. "
            "Key areas: budget, delivery timeline, scope, and quality standards."
        ),
        "agents": [
            {"id": "agent-a", "name": "Agent A"},
            {"id": "agent-b", "name": "Agent B"},
        ],
        "n_steps": 200,
    }
    msg = _envelope("agent-a", payload)
    msg["_comment"] = (
        "POST /api/v1/negotiate/initiate — start negotiation from content_text + agents"
    )
    # Validate round-trip
    SSTPNegotiateMessage.model_validate(msg)
    return msg


def _example_offer_accept() -> dict:
    payload = {
        "round": 3,
        "action": "accept",
        "trace": _EXAMPLE_TRACE,
    }
    msg = _envelope("agent-b", payload)
    msg["_comment"] = "POST /api/v1/negotiate/offer-response — Agent B accepts round 3 offer"
    SSTPNegotiateMessage.model_validate(msg)
    return msg


def _example_offer_reject() -> dict:
    payload = {
        "round": 2,
        "action": "reject",
        "trace": _EXAMPLE_TRACE,
    }
    msg = _envelope("agent-b", payload)
    msg["_comment"] = "POST /api/v1/negotiate/offer-response — Agent B rejects, ends negotiation"
    SSTPNegotiateMessage.model_validate(msg)
    return msg


_EXAMPLE_BUILDERS = {
    "initiate": _example_initiate,
    "offer-accept": _example_offer_accept,
    "offer-reject": _example_offer_reject,
}


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="python -m app.agents.protocol.sstp",
        description="Dump SSTP JSON Schema(s) or example messages to stdout",
    )
    parser.add_argument(
        "kind",
        nargs="?",
        choices=[*list(_KINDS), "all"],
        default="all",
        metavar="KIND",
        help=(
            f"Schema kind to dump: {{{', '.join(_KINDS)}}} or 'all'. "
            "Ignored when --examples is used. Default: all"
        ),
    )
    parser.add_argument(
        "--examples",
        nargs="?",
        const="all",
        choices=_EXAMPLE_CHOICES,
        metavar="EXAMPLE",
        help=(
            "Dump example SSTPNegotiateMessage payloads instead of schemas. "
            f"Choices: {_EXAMPLE_CHOICES}. Default when flag given: all"
        ),
    )
    parser.add_argument(
        "--indent",
        type=int,
        default=2,
        metavar="N",
        help="JSON indentation level (default: 2; use 0 for compact)",
    )
    args = parser.parse_args()

    # ── examples mode ────────────────────────────────────────────────────────
    if args.examples is not None:
        if args.examples == "all":
            out = [builder() for builder in _EXAMPLE_BUILDERS.values()]
        else:
            out = [_EXAMPLE_BUILDERS[args.examples]()]
        return

    # ── schema mode (default) ────────────────────────────────────────────────
    if args.kind == "all":
        out: dict = {"$sstp_version": __version__}
        for name, cls in _KINDS.items():
            out[name] = cls.model_json_schema()
        out["$union:STPMessage"] = TypeAdapter(STPMessage).json_schema()
    else:
        cls = _KINDS[args.kind]
        schema = cls.model_json_schema()
        schema["$sstp_version"] = __version__


if __name__ == "__main__":
    main()
