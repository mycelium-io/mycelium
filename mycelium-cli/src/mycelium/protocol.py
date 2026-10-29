# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""
Lightweight models for the CLI: agent and user manifests, and memory keys.

These mirror shapes the hub validates so the CLI can check them without
importing the backend package.

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

import re
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, Field, ValidationInfo, field_validator, model_validator

# Two shape rules. A *handle* is an identity and can be minted by a real IdP, so it
# allows the `@` a corporate SSO `preferred_username` carries (e.g.
# `user@example.com`). A *slug* is a filename / composer trigger token (memory keys,
# skill names) and stays clean. Keep this copy in agreement with the backend
# (`app/schemas.py`, `app/routes/engines.py`) and the frontend
# (`acting-as-picker.tsx`); the thin CLI can't import the backend.
HANDLE_PATTERN = r"^[a-z0-9][a-z0-9._@-]*$"
SLUG_PATTERN = r"^[a-z0-9][a-z0-9._-]*$"

# Engines run backend-side only. ``host`` coerces to ``backend`` for legacy config.
EngineRuntime = Literal["backend"]


# ── Memory protocol ──────────────────────────────────────────────────────────


class MemoryCategory(StrEnum):
    """Structured memory categories: key prefix conventions for room memories.

    These are the recommended top-level namespaces for persistent memories.
    Using typed categories instead of raw strings gives CLI validation, tab
    completion, and structure-aware synthesis.
    """

    WORK = "work"
    DECISIONS = "decisions"
    CONTEXT = "context"
    STATUS = "status"
    PROCEDURES = "procedures"


MEMORY_CATEGORIES: frozenset[str] = frozenset(c.value for c in MemoryCategory)

# Labels used by both CLI (category commands) and backend (synthesis grouping).
# Single source of truth; backend imports this dict.
STRUCTURED_CATEGORY_LABELS: dict[str, str] = {
    "work": "Work Done",
    "decisions": "Decisions Made",
    "context": "Background & Preferences",
    "status": "Current Status",
}


#: Categories whose keys may have folders of their own. The others' keys are
#: board rows, one name each.
NESTED_CATEGORIES: frozenset[str] = frozenset({"context", "procedures"})


class MemoryLogEntry(BaseModel):
    """Typed payload for structured memory writes.

    Validates that a memory write follows the category/slug convention before
    hitting the API.

    Slugs are auto-lowercased so agents can write naturally (e.g. "API-latency"
    becomes "api-latency"). Under ``context/`` and ``procedures/`` a slug can
    have folders of its own (``context/api/latency``), each part a slug. Under
    ``work/``, ``decisions/`` and ``status/`` it's one name: every key there is
    a row on the board.

    Examples:
        MemoryLogEntry(category="work", slug="cron-setup", content="Created crontab ...")
        MemoryLogEntry(category="status", slug="deploy", content="ACTIVE")
        MemoryLogEntry(category="decisions", slug="db-choice", content="Chose AgensGraph ...")
        MemoryLogEntry(category="context", slug="api/latency", content="p99 under 200ms")
    """

    category: Literal["work", "decisions", "context", "status", "procedures"]
    slug: str = Field(..., min_length=1)
    content: str = Field(..., min_length=1)
    tags: list[str] | None = None

    @model_validator(mode="before")
    @classmethod
    def lowercase_slug(cls, data: dict) -> dict:
        if isinstance(data, dict) and "slug" in data:
            data["slug"] = data["slug"].lower()
        return data

    @field_validator("slug")
    @classmethod
    def slug_parts(cls, slug: str, info: ValidationInfo) -> str:
        parts = slug.split("/")
        category = info.data.get("category")
        # Each message follows the key in the CLI's error, and leads with what to do.
        if len(parts) > 1 and category not in NESTED_CATEGORIES:
            msg = (
                f"can't have folders: a {category}/ key is a row on the board, so it takes "
                f"one name. Try {category}/{'-'.join(p for p in parts if p)}."
            )
            raise ValueError(msg)
        if not all(re.fullmatch(SLUG_PATTERN, p) for p in parts):
            msg = (
                "has an empty or invalid part. Each part between slashes starts with a "
                "lowercase letter or digit and uses only a-z, 0-9, -, _ and ."
            )
            raise ValueError(msg)
        return slug

    @property
    def key(self) -> str:
        """Full memory key: category/slug."""
        return f"{self.category}/{self.slug}"


# ── Agent primitive ──────────────────────────────────────────────────────────


# Adapter identifiers the agent primitive knows how to host:
#   claude_code → a resident Claude Code session (kept woken with `await --loop`)
#   cursor      → a resident Cursor session (same resident lifecycle)
#   engine      → a first-party cognition engine the backend runs
#   a2a         → an external Agent2Agent endpoint, driven by a backend-held seat
AGENT_ADAPTERS: frozenset[str] = frozenset({"claude_code", "cursor", "engine", "a2a"})

#: Cognition-engine kinds hosted by the first-party ``engine`` runtime family,
#: the same set the hub's ``routes/engines.py`` accepts. ``conductor`` walks a
#: flow through a task's thread (negotiation is its ``concord`` and ``accord``
#: flows), ``synthesizer`` distills room memory, ``hello`` is one Pi turn with no
#: side effects (the cheap proof the engine path works); no new adapter per kind.
ENGINE_KINDS: frozenset[str] = frozenset(
    {"conductor", "hello", "persona", "synthesizer", "verifier", "worker"}
)

#: Engine kinds the hub no longer runs, with what to run instead. A room made
#: before a kind was retired can still hold its manifest, so a manifest naming
#: one still loads (it can be listed and removed); creating a new one is refused
#: with this text, the same answer the hub gives.
RETIRED_ENGINE_KINDS: dict[str, str] = {
    "aligner": (
        "The aligner was retired, so nothing started. To negotiate, run "
        '`mycelium board coordinate <row> conductor "concord …"` to help members '
        'agree, or `"accord …"` to get them on the same page.'
    ),
}


class AgentManifest(BaseModel):
    """Typed payload for an ``agents/<handle>`` memory entry.

    Each Mycelium agent is just a memory entry under ``agents/<handle>`` plus a
    notes blob under ``agents/<handle>/notes``. This model validates the
    manifest body, the bare minimum a dispatcher needs to route an
    ``@handle`` mention to the agent's runtime.

    Adapters:

    - ``claude_code``: a resident Claude Code session (kept woken with
      ``mycelium await --loop``). Optional ``cwd`` (the session's working dir).
    - ``cursor``: a resident Cursor session. Optional ``cwd`` (Cursor's workspace
      root; also where workspace assets drop when set).
    - ``engine``: a first-party cognition engine (e.g. ``conductor``), run by the
      backend. Requires ``kind``.

    The handle doubles as the mention target (``@release-agent``). It follows the
    lowercase ``HANDLE_PATTERN`` — like a memory slug but also allowing ``@``, so
    an IdP-minted email identity (``user@example.com``) is a valid handle.
    """

    handle: str = Field(..., min_length=1, pattern=HANDLE_PATTERN)
    adapter: Literal["claude_code", "cursor", "engine", "a2a"] = "claude_code"
    kind: str | None = Field(
        default=None,
        description=(
            "engine: which cognition engine this handle runs (e.g. 'conductor'). "
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
    a2a_card: str | None = Field(
        default=None,
        description="a2a: base URL of the remote Agent Card. Required for the a2a adapter.",
    )
    a2a_endpoint: str | None = Field(
        default=None,
        description="a2a: resolved RPC endpoint the backend-held seat calls.",
    )
    a2a_skills: list[str] = Field(
        default_factory=list,
        description="a2a: skill ids advertised by the remote card (for the roster).",
    )
    framework: str | None = Field(
        default=None,
        description=(
            "The agent CLI it runs, as herdr names its kind (claude, codex, pi…), "
            "when known. The adapter is how it takes part in a room; this is what it is."
        ),
    )
    runner: str | None = Field(
        default=None,
        description="The machine whose runner started it, for an agent a runner started.",
    )

    @model_validator(mode="before")
    @classmethod
    def lowercase_handle(cls, data: dict) -> dict:
        if not isinstance(data, dict):
            return data
        # Handle and the two principal pointers are all lowercase slugs; an
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
        # guard (the backend routes on this). A retired kind still loads, so a
        # room's old manifest can be listed and removed.
        if self.adapter == "engine":
            if not (self.kind and self.kind.strip()):
                raise ValueError("engine agents require a 'kind' (e.g. 'conductor')")
            if self.kind not in ENGINE_KINDS and self.kind not in RETIRED_ENGINE_KINDS:
                raise ValueError(
                    f"unknown engine kind {self.kind!r}; known: {sorted(ENGINE_KINDS)}"
                )
        # An a2a agent is a remote endpoint: its manifest must name the card so
        # the backend-held seat knows who to call.
        if self.adapter == "a2a" and not (self.a2a_card and self.a2a_card.strip()):
            raise ValueError("a2a agents require an 'a2a_card' (the remote Agent Card URL)")
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
    room-scoped. Trust is self-asserted; the handle is consistent, not
    cryptographic.
    """

    handle: str = Field(..., min_length=1, pattern=HANDLE_PATTERN)
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
