# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""
Lightweight SSTP (Semantic State Transfer Protocol) models for the CLI.

These models mirror the wire format used by Mycelium's coordination layer so
the CLI can validate outgoing agent replies and parse incoming coordination
ticks without importing the full backend package.

Agent reply shapes (agent → server, plain JSON in room message content):

    # Reply to a "propose" tick
    { "offer": { "budget": "medium", "timeline": "standard" } }

    # Reply to a "respond" tick
    { "action": "accept" }   # or "reject" or "end"

    Both reply shapes accept optional epistemic fields (L9/SIEP):
    ``confidence`` (float 0-1), ``reasoning`` (string), and the 3-way evidence
    split from the spec's ``proposal_payload`` -- ``supporting_evidence`` /
    ``against_evidence`` (lists of non-empty strings) plus ``addresses`` (the
    prior evidence keys this turn engages, the input to the grounding check).
    ``respond`` additionally accepts ``revision_cause`` (why the belief moved:
    ``grounded_argument`` / ``social_compliance`` / ``new_evidence`` /
    ``semantic_memory`` / ``repair_resolution``) and ``deferred_to`` (the handle
    you yielded to on a compliance accept). The legacy flat ``evidence`` list
    still parses. Every epistemic field is optional -- an agent that sends none
    negotiates exactly as before. Omitted fields MUST be absent from the
    serialized JSON, not null, so legacy replies stay byte-identical (so always
    serialize with ``model_dump(exclude_none=True)``).

Inbound tick shape (server → agent, coordination_tick message content):
The content field is a JSON-serialised SSTPNegotiateMessage envelope whose
``payload`` carries the negotiation action details (see NegotiatePayload).

Memory protocol shapes (agent → memory API, structured key conventions):

    # Structured memory with category prefix
    key = "work/cron-setup"       → work agent did
    key = "decisions/db-choice"   → why a choice was made
    key = "context/user-goal"     → background / preferences
    key = "status/deploy"         → current state of something
    key = "procedures/url-monitor" → reusable how-to steps

    The MemoryLogEntry model validates the category/slug convention.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator

# Why an agent's stated belief moved this turn (SIEP `belief.revision_cause`).
# ``social_compliance`` is the one that drives SCR down; the rest are genuine.
RevisionCause = Literal[
    "grounded_argument",
    "social_compliance",
    "new_evidence",
    "semantic_memory",
    "repair_resolution",
]

# Where a registered engine runs its NEGMAS drive. The ``host`` runtime rode the
# (now-removed) daemon; engines run backend-side only. Retained as a single-value
# type so config plumbing stays stable and legacy ``host`` coerces to ``backend``.
EngineRuntime = Literal["backend"]


def _validate_evidence(evidence: list[str] | None) -> list[str] | None:
    """Reject empty/whitespace-only evidence strings (shared by both replies)."""
    if evidence is not None:
        for item in evidence:
            if not item.strip():
                msg = "evidence items must be non-empty strings"
                raise ValueError(msg)
    return evidence


class RespondReply(BaseModel):
    """Agent → Server reply to a 'respond' coordination tick.

    CFN mode: action is "accept" or "reject".
    Inline NegMAS mode: "end" is also accepted (mapped to "reject" by backend).

    Epistemic fields (confidence, supporting/against_evidence, addresses,
    revision_cause, deferred_to, reasoning) are optional; ``offer`` is only
    meaningful for ``counter_offer``. Unset fields must be absent from the wire
    JSON: serialize with ``model_dump(exclude_none=True)``.
    """

    action: Literal["accept", "reject", "end", "counter_offer"]
    offer: dict[str, str] | None = Field(
        default=None,
        description="Counter-offer issue assignments (only valid for action=counter_offer).",
    )
    confidence: float | None = Field(
        default=None,
        ge=0.0,
        le=1.0,
        description="Self-reported confidence in this response, 0-1.",
    )
    evidence: list[str] | None = Field(
        default=None,
        description="Legacy flat evidence list; prefer supporting/against_evidence.",
    )
    supporting_evidence: list[str] | None = Field(
        default=None,
        description="Evidence keys arguing FOR this response (non-empty strings).",
    )
    against_evidence: list[str] | None = Field(
        default=None,
        description="Known counter-evidence keys arguing against this response.",
    )
    addresses: list[str] | None = Field(
        default=None,
        description="Prior evidence keys this response engages (feeds grounding).",
    )
    revision_cause: RevisionCause | None = Field(
        default=None,
        description="Why the stated belief moved this turn (SIEP belief.revision_cause).",
    )
    deferred_to: str | None = Field(
        default=None,
        min_length=1,
        description="Handle of the agent yielded to on a compliance accept (feeds SCR).",
    )
    reasoning: str | None = Field(
        default=None,
        description="Free-text rationale for the response.",
    )

    @field_validator("evidence", "supporting_evidence", "against_evidence", "addresses")
    @classmethod
    def check_evidence(cls, v: list[str] | None) -> list[str] | None:
        return _validate_evidence(v)

    @model_validator(mode="after")
    def check_offer_only_for_counter(self) -> RespondReply:
        if self.offer is not None and self.action != "counter_offer":
            msg = "offer is only valid with action=counter_offer"
            raise ValueError(msg)
        return self


class TeamPrior(BaseModel):
    """Optional ``team_prior`` block on an inbound tick payload.

    Injected by the backend when a knowledge query returns prior agreements
    on the room's topic (L9 knowledge path).
    """

    confidence: float
    provenance_weight: float
    episode_count: int
    source: str | None = None


class ConsensusMetrics(BaseModel):
    """Optional ``metrics`` block on a ``coordination_consensus`` message.

    Interim agreement-quality metrics (SIEP): mpc = mean final confidence,
    gar = grounded-agreement ratio, scr = social-compliance ratio.
    """

    mpc: float
    gar: float
    scr: float
    provenance_weight: float
    participants: int


class ConsensusContent(BaseModel):
    """Minimal shape of a ``coordination_consensus`` message content.

    The CLI passes most consensus keys through untyped; this model exists so
    consumers that want validation of the new L9 fields have one.
    """

    plan: str | None = None
    plan_file: str | None = None
    assignments: dict[str, Any] | None = None
    broken: bool = False
    metrics: ConsensusMetrics | None = None
    cfn_persisted: bool | None = None


class NegotiatePayload(BaseModel):
    """Payload extracted from an inbound SSTPNegotiateMessage coordination_tick.

    Maps to the ``payload`` field of the SSTP envelope sent by RoomNegotiator.
    """

    kind: str = "negotiate"
    action: Literal["propose", "respond"]
    session_id: str
    participant_id: str
    round: int
    issue_options: dict[str, list[str]] = Field(default_factory=dict)
    current_offer: dict[str, str] | None = None
    proposer_id: str | None = None
    history: list[dict[str, Any]] = Field(default_factory=list)
    n_steps: int | None = None
    team_prior: TeamPrior | None = None
    l9: dict[str, Any] | None = None


class InboundTick(BaseModel):
    """Minimal SSTP envelope shape for parsing inbound coordination_tick content.

    The full backend envelope has many more fields (origin, policy_labels, etc.).
    The CLI only needs ``kind`` and ``payload`` for display and reply validation.
    """

    kind: str = "negotiate"
    payload: NegotiatePayload


# ── Memory protocol ──────────────────────────────────────────────────────────


class MemoryCategory(StrEnum):
    """Structured memory categories — key prefix conventions for room memories.

    These are the recommended top-level namespaces for persistent memories.
    Using typed categories instead of raw strings gives CLI validation, tab
    completion, and structure-aware synthesis.
    """

    WORK = "work"
    DECISIONS = "decisions"
    CONTEXT = "context"
    STATUS = "status"
    PROCEDURES = "procedures"
    PLAN = "plan"


MEMORY_CATEGORIES: frozenset[str] = frozenset(c.value for c in MemoryCategory)

# Labels used by both CLI (category commands) and backend (synthesis grouping).
# Single source of truth — backend imports this dict.
STRUCTURED_CATEGORY_LABELS: dict[str, str] = {
    "work": "Work Done",
    "decisions": "Decisions Made",
    "context": "Background & Preferences",
    "status": "Current Status",
    "plan": "Plan & Open Tasks",
}


class MemoryLogEntry(BaseModel):
    """Typed payload for structured memory writes.

    Validates that a memory write follows the category/slug convention before
    hitting the API.

    Slugs are auto-lowercased so agents can write naturally (e.g. "API-latency"
    becomes "api-latency").

    Examples:
        MemoryLogEntry(category="work", slug="cron-setup", content="Created crontab ...")
        MemoryLogEntry(category="status", slug="deploy", content="ACTIVE")
        MemoryLogEntry(category="decisions", slug="db-choice", content="Chose AgensGraph ...")
    """

    category: Literal["work", "decisions", "context", "status", "procedures", "plan"]
    slug: str = Field(..., min_length=1, pattern=r"^[a-z0-9][a-z0-9._-]*$")
    content: str = Field(..., min_length=1)
    tags: list[str] | None = None

    @model_validator(mode="before")
    @classmethod
    def lowercase_slug(cls, data: dict) -> dict:
        if isinstance(data, dict) and "slug" in data:
            data["slug"] = data["slug"].lower()
        return data

    @property
    def key(self) -> str:
        """Full memory key: category/slug."""
        return f"{self.category}/{self.slug}"


# ── Agent primitive ──────────────────────────────────────────────────────────


# Adapter identifiers the agent primitive knows how to host:
#   claude_code → a resident Claude Code session (kept woken with `await --loop`)
#   cursor      → a resident Cursor session (same resident lifecycle)
#   engine      → a first-party cognition engine the backend runs
AGENT_ADAPTERS: frozenset[str] = frozenset({"claude_code", "cursor", "engine"})

#: Cognition-engine kinds hosted by the first-party ``engine`` runtime family.
#: The extensibility axis: ``aligner`` (SIEP converge) and ``synthesizer`` (room
#: memory → structured summary) today; ``bargainer`` (SAB), ``team_former`` (TFP),
#: a drift evaluator, etc. later — no new adapter per CE.
ENGINE_KINDS: frozenset[str] = frozenset({"aligner", "synthesizer"})


class AgentManifest(BaseModel):
    """Typed payload for an ``agents/<handle>`` memory entry.

    Each Mycelium agent is just a memory entry under ``agents/<handle>`` plus a
    notes blob under ``agents/<handle>/notes``. This model validates the
    manifest body — the bare minimum a dispatcher needs to route an
    ``@handle`` mention to the agent's runtime.

    Adapters:

    - ``claude_code`` — a resident Claude Code session (kept woken with
      ``mycelium await --loop``). Optional ``cwd`` (the session's working dir).
    - ``cursor`` — a resident Cursor session. Optional ``cwd`` (Cursor's workspace
      root; also where workspace assets drop when set).
    - ``engine`` — a first-party cognition engine (e.g. ``aligner``), run by the
      backend. Requires ``kind``.

    The handle slug doubles as the mention target (``@release-agent``), so it
    must match the same lowercase pattern other memory slugs use.
    """

    handle: str = Field(..., min_length=1, pattern=r"^[a-z0-9][a-z0-9._-]*$")
    adapter: Literal["claude_code", "cursor", "engine"] = "claude_code"
    kind: str | None = Field(
        default=None,
        description=(
            "engine: which cognition engine this handle runs (e.g. 'aligner'). "
            "Required for the ``engine`` adapter; unused by other families. The "
            "extensibility axis for the first-party CE family."
        ),
    )
    cwd: str | None = Field(
        default=None,
        description=(
            "claude_code / cursor: optional working dir for the resident session. "
            "Cursor treats it as the workspace root (and asset drop site) when set."
        ),
    )
    description: str = Field(default="", description="One-paragraph purpose statement.")
    owner: str | None = Field(
        default=None,
        description=(
            "User (a `users/<handle>` in the global store) this agent belongs to. "
            "Self-asserted: consistent, not cryptographic. None means unowned."
        ),
    )
    team: str | None = Field(
        default=None,
        description=(
            "Team slug this agent is fielded by; self-asserted. Scopes 'my team' filtering."
        ),
    )
    allow_from: list[str] = Field(
        default_factory=list,
        description=(
            "Sender handles allowed to invoke this agent (e.g. ['@avery', '@docs-agent']). "
            "Empty list means anyone in the room can invoke. "
            "Also the 'act on behalf of' grant: with the hub's auth gate enabled, these "
            "handles (and the owner) may await or join as this agent; an empty list "
            "grants no one."
        ),
    )

    @model_validator(mode="before")
    @classmethod
    def lowercase_handle(cls, data: dict) -> dict:
        if not isinstance(data, dict):
            return data
        # Handle and the two principal pointers are all lowercase slugs — an
        # owner/team is a `users/<handle>` / team slug, so `--owner Avery`
        # binds to `users/avery`. The handle is required, so an empty result
        # stays a string (and fails the pattern); owner/team collapse to None.
        for field in ("handle", "owner", "team"):
            value = data.get(field)
            if not isinstance(value, str):
                continue
            normalized = value.strip().lstrip("@").lower()
            if field == "handle":
                data[field] = normalized
            else:
                data[field] = normalized or None
        return data

    @model_validator(mode="after")
    def check_adapter_requirements(self) -> AgentManifest:
        # cwd is optional: it's the resident session's working dir / cursor's
        # workspace root (used for asset drops when set), not a launch requirement.
        # A cognition engine must name which CE it runs; unknown kinds are a typo
        # guard (the backend routes on this).
        if self.adapter == "engine":
            if not (self.kind and self.kind.strip()):
                raise ValueError("engine agents require a 'kind' (e.g. 'aligner')")
            if self.kind not in ENGINE_KINDS:
                raise ValueError(
                    f"unknown engine kind {self.kind!r}; known: {sorted(ENGINE_KINDS)}"
                )
        return self

    @property
    def memory_key(self) -> str:
        """Memory key the manifest is stored under."""
        return f"agents/{self.handle}"

    @property
    def notes_key(self) -> str:
        """Memory key the agent's persistent notes are stored under."""
        return f"agents/{self.handle}/notes"


# ── User primitive ───────────────────────────────────────────────────────────


class UserManifest(BaseModel):
    """Typed payload for a global ``users/<handle>`` record.

    The human, made first-class and symmetric with ``agents/<handle>``. An
    agent's ``owner`` points here; a ``team`` groups these handles. People span
    rooms, so this store is global (``~/.mycelium/users/<handle>``), not
    room-scoped. Trust is self-asserted — the handle is consistent, not
    cryptographic.
    """

    handle: str = Field(..., min_length=1, pattern=r"^[a-z0-9][a-z0-9._-]*$")
    display_name: str = Field(default="", description="Human-readable name, e.g. 'Avery Quinn'.")
    teams: list[str] = Field(
        default_factory=list,
        description="Team slugs this person belongs to. Scopes 'my team' views.",
    )
    notify: str | None = Field(
        default=None,
        description="Where to route 'needs you' escalations (e.g. an email or webhook). Optional.",
    )

    @model_validator(mode="before")
    @classmethod
    def normalize(cls, data: dict) -> dict:
        if not isinstance(data, dict):
            return data
        handle = data.get("handle")
        if isinstance(handle, str):
            data["handle"] = handle.strip().lstrip("@").lower()
        teams = data.get("teams")
        if isinstance(teams, list):
            data["teams"] = [t.strip().lstrip("@").lower() for t in teams if str(t).strip()]
        return data

    @property
    def memory_key(self) -> str:
        """Store key (relative to the global users dir)."""
        return self.handle
