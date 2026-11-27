# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""
Configuration management for Mycelium CLI.

Supports two config locations (like git):
1. Global: ~/.mycelium/config.toml - identity, server settings
2. Project-local: ./.mycelium/config.toml - room settings

Load priority (highest to lowest):
1. Command-line flags
2. Environment variables
3. Project-local config (./.mycelium/)
4. Global config (~/.mycelium/)
5. Defaults
"""

import os
import re
from pathlib import Path
from typing import Any, ClassVar, Literal

import toml
from pydantic import BaseModel, Field, field_validator, model_validator

from mycelium.protocol import EngineRuntime

# Header key prepended to every ~/.mycelium/config.json write. Strict JSON has no
# comment syntax; ``"//"`` is the npm/package.json convention for documentation
# keys and every consumer ignores it (they look up known sections by name). The
# key leads so it's the first thing a user sees on `cat`.
_JSON_HEADER_KEY = "//"
_JSON_HEADER_VALUE = (
    "DO NOT EDIT: auto-generated from ~/.mycelium/config.toml on every save. "
    "Edit config.toml instead, or use `mycelium config set`. "
    "Any edits here are silently overwritten on the next save."
)


class IdentityConfig(BaseModel):
    """Agent identity configuration."""

    name: str | None = Field(
        default=None,
        description="Display name chosen by user",
    )
    machine_id: str | None = Field(
        default=None,
        description="Stable UUID for machine affinity (generated on first use)",
    )
    autonomous: bool = Field(
        default=False,
        description="True when running as an autonomous agent",
    )


class ServerConfig(BaseModel):
    """Server connection configuration."""

    api_url: str = Field(
        default="http://localhost:8000",
        description="Mycelium backend API URL",
    )

    @field_validator("api_url")
    @classmethod
    def validate_url(cls, v: str) -> str:
        """Ensure URLs don't have trailing slashes."""
        return v.rstrip("/")


class LLMConfig(BaseModel):
    """LLM configuration ("provider/model" format)."""

    model: str | None = Field(
        default=None,
        description="LLM model in provider/model format (e.g. anthropic/claude-sonnet-4-6)",
    )
    api_key: str | None = Field(
        default=None,
        description="API key for the LLM provider",
    )
    base_url: str | None = Field(
        default=None,
        description="Custom base URL for LLM endpoint (ollama, vllm, etc.)",
    )


class EngineConfig(BaseModel):
    """First-party Cognition Engine runtime configuration.

    ``runtime`` is ``backend``-only: the always-on backend owns a registered
    engine's run via its summon seam. (The ``host`` runtime rode the daemon,
    which has been removed; legacy ``host`` config coerces to ``backend``.)
    """

    runtime: EngineRuntime = Field(
        default="backend",
        description="Where registered engines run their drive (backend-only).",
    )

    @field_validator("runtime", mode="before")
    @classmethod
    def _normalize_runtime(cls, v: object) -> object:
        # Normalize casing/whitespace; coerce 'host' to 'backend' for backward compatibility.
        if isinstance(v, str):
            normalized = v.strip().lower()
            return "backend" if normalized == "host" else normalized
        return v


class TrustedIssuer(BaseModel):
    """One trust root the backend's HTTP-API gate accepts tokens from.

    Configured as a repeatable ``[[auth.issuers]]`` block. More than one root is
    the normal case (a human OIDC issuer alongside an agent/service-account one),
    and each carries its own keys, audience, and default role, so adding a root
    is config rather than code.
    """

    issuer: str = Field(
        ...,
        description="Exact `iss` claim value to trust, e.g. https://idp.example.com/realms/mycelium",
    )
    jwks_url: str | None = Field(
        default=None,
        description="JWKS URL for this issuer. Omit to resolve it from the issuer's OIDC discovery document.",
    )
    audience: str | None = Field(
        default=None,
        description="Required `aud` for tokens from this issuer; overrides auth.audience.",
    )
    role: str = Field(
        default="agent",
        description="Role ('user' or 'agent') for principals from this issuer when the token carries no role claim.",
    )

    @field_validator("role")
    @classmethod
    def _validate_role(cls, v: str) -> str:
        normalized = v.strip().lower()
        if normalized not in ("user", "agent"):
            raise ValueError("role must be 'user' or 'agent'")
        return normalized

    @field_validator("issuer", "jwks_url")
    @classmethod
    def _strip_trailing_slash(cls, v: str | None) -> str | None:
        return v.rstrip("/") if isinstance(v, str) else v


class AuthConfig(BaseModel):
    """HTTP-API JWT gate, off by default.

    The backend validates a bearer token against a configured issuer + JWKS. It
    ships **disabled**: auth must never stand between someone and trying
    Mycelium, so the default stack needs no issuer and no tokens. Turning it on
    is a per-deployment decision for when a team shares a hub over a network.

    When enabling it, set ``audience`` as well. Without one, *any* token a
    trusted issuer ever minted is accepted, including tokens a user obtained
    for an unrelated application on the same IdP. The audience is what makes
    "valid token" mean "token meant for this hub".
    """

    enabled: bool = Field(
        default=False,
        description="Enforce bearer-token auth on the backend HTTP API.",
    )
    issuers: list[TrustedIssuer] = Field(
        default_factory=list,
        description="Trust roots, as repeatable [[auth.issuers]] blocks.",
    )
    audience: str | None = Field(
        default=None,
        description="Required `aud` claim for every token. Strongly recommended whenever auth is enabled; unset means the audience is not checked.",
    )
    localhost_bypass: bool = Field(
        default=True,
        description="Let loopback callers through without a token, so enabling auth can't lock an operator out of the hub machine. Does not apply to a backend in Docker, whose callers arrive from the bridge gateway rather than loopback.",
    )
    handle_claim: str = Field(
        default="sub",
        description="Token claim carrying the canonical @handle.",
    )
    role_claim: str = Field(
        default="mycelium_role",
        description="Token claim distinguishing a user from an agent.",
    )
    leeway_s: float = Field(
        default=60.0,
        description="Clock-skew allowance in seconds on exp/nbf/iat.",
    )
    jwks_ttl_s: float = Field(
        default=300.0,
        description="How long a fetched JWKS is cached before re-fetch. Key rotation is also picked up on an unseen kid.",
    )


class LoginConfig(BaseModel):
    """Where ``mycelium login`` gets a human's token: the client side of auth.

    Distinct from :class:`AuthConfig`, which configures the *hub's* gate: this
    section says which issuer this machine logs in against, that one says which
    issuers the backend trusts. A spoke needs only this half.

    Unset ``issuer`` means "no login configured", which is the default: the CLI
    sends no token and behaves exactly as it does with no identity at all.
    """

    issuer: str | None = Field(
        default=None,
        description="OIDC issuer to log in against, e.g. https://sso.example.com/realms/mycelium",
    )
    client_id: str = Field(
        default="mycelium-cli",
        description="OAuth client id registered for the CLI at that issuer.",
    )
    client_secret: str | None = Field(
        default=None,
        description="Client secret, only for issuers that refuse public clients. PKCE means the CLI normally needs none.",
    )
    scopes: str = Field(
        default="openid profile email offline_access",
        description="Space-separated scopes to request. 'offline_access' is what gets a refresh token from most issuers.",
    )
    audience: str | None = Field(
        default=None,
        description="Audience to request for the token; should match the hub's auth.audience.",
    )
    redirect_port: int = Field(
        default=0,
        description="Fixed loopback port for the browser redirect (0 = pick a free one). Set this when the issuer requires an exact registered redirect URI.",
    )

    @field_validator("issuer")
    @classmethod
    def _strip_trailing_slash(cls, v: str | None) -> str | None:
        return v.rstrip("/") if isinstance(v, str) else v


class AgentAuthConfig(BaseModel):
    """Where an *agent* gets its own token: the workload half of the client side.

    An agent is not a human: no browser, no consent screen, and nobody to run
    ``mycelium login`` on its behalf. Its credential is its own OIDC client
    (``client_credentials``), so the token's ``sub`` is the client id, which is
    the agent's handle, the same handle the hub binds its writes to.

    This section holds only what is *shared* by every agent on the machine (the
    issuer and the audience to ask for). The per-agent half (which client id an
    agent is, and its secret) is a secret, so it lives in the ``0600`` store
    behind ``mycelium agent credential set``, never in ``config.toml``.

    Unset ``issuer`` means "no agent credentials configured", which is the
    default: agents send no token, exactly as before.
    """

    issuer: str | None = Field(
        default=None,
        description="OIDC issuer agents mint their service-account tokens from. Unset (default) means agents send no token.",
    )
    scopes: str | None = Field(
        default=None,
        description="Space-separated scopes to request for an agent token. Unset sends none, which is what most issuers want for client_credentials.",
    )
    audience: str | None = Field(
        default=None,
        description="Audience to request for agent tokens; should match the hub's auth.audience.",
    )

    @field_validator("issuer")
    @classmethod
    def _strip_trailing_slash(cls, v: str | None) -> str | None:
        return v.rstrip("/") if isinstance(v, str) else v


class RuntimeConfig(BaseModel):
    """Docker runtime / environment configuration."""

    bind_addr: str = Field(
        default="127.0.0.1",
        description=(
            "Host address the Docker stack publishes its ports on "
            "(MYCELIUM_BIND_ADDR). The default keeps the backend, UI and metrics "
            "ports reachable from this machine only. A hub that serves spokes on "
            "other machines needs '0.0.0.0', and should have authentication on "
            "first. Example: mycelium config set runtime.bind_addr 0.0.0.0"
        ),
    )
    backend_port: int = Field(
        default=8000,
        description="Host port for the backend API",
    )
    collector_port: int = Field(
        default=4318,
        description="Host port for the OTLP metrics collector",
    )
    frontend_port: int = Field(
        default=3000,
        description="Host port for the frontend UI",
    )
    allowed_dev_origins: str = Field(
        default="",
        description=(
            "Comma-separated origins the Next.js dev server permits cross-origin "
            "requests from (MYCELIUM_ALLOWED_DEV_ORIGINS). Add your public IP or "
            "hostname when running `mycelium up` (or pnpm dev) behind a reverse "
            "proxy or NAT and accessing the UI from a browser on a different host. "
            "Production Docker builds do not use this — the browser always hits its "
            "own origin. Example: mycelium config set runtime.allowed_dev_origins "
            "'3.139.30.16' or '3.139.30.16,10.0.0.5'"
        ),
    )
    data_dir: str | None = Field(
        default=None,
        description="Root directory for .mycelium/ data (defaults to ~/.mycelium)",
    )
    trusted_proxies: str = Field(
        default="",
        description=(
            "Which forwarders the backend may believe about the original request "
            "(rendered as uvicorn's FORWARDED_ALLOW_IPS). Empty (the default) trusts "
            "only loopback, so a direct caller cannot spoof X-Forwarded-Proto and "
            "make the hub advertise a scheme it is not served on. Set it when a "
            "TLS-terminating reverse proxy fronts the backend, otherwise every "
            "absolute URL the hub generates (the A2A agent card's `url` most "
            "visibly) comes out http:// on an https:// deployment. Use '*' when the "
            "backend is only reachable through that proxy, or a comma-separated list "
            "of proxy addresses. Example: mycelium config set "
            "runtime.trusted_proxies '*'"
        ),
    )


class HerdrConfig(BaseModel):
    """Optional herdr persistent-runtime wake layer.

    herdr (https://herdr.dev) keeps coding-agent sessions alive and addressable.
    When ``autowake`` is on, a non-resident ``agent invoke`` tries to wake the
    handle's mapped herdr pane (``mycelium herdr map``) instead of only queuing on
    the durable cursor. Off by default and always fail-soft: a missing/unreachable
    herdr, or an unmapped/busy agent, falls straight back to the cursor behavior.
    """

    autowake: bool = Field(
        default=False,
        description="On a non-resident `agent invoke`, wake the handle's mapped herdr pane.",
    )
    wake_timeout_ms: int = Field(
        default=120000,
        description="Wait budget (ms) for a herdr wake to settle.",
    )
    panes_per_tab: int = Field(
        default=4,
        ge=1,
        description=(
            "How many agent panes a herdr tab holds before the next agent opens a new tab "
            "in the room's workspace."
        ),
    )


class RunnerConfig(BaseModel):
    """Where this machine's runner starts the agents the app asks for."""

    host: Literal["herdr", "omnigent"] = Field(
        default="herdr",
        description="The host this machine's runner starts agents on.",
    )
    omnigent_url: str = Field(
        default="http://127.0.0.1:6767",
        description="The Omnigent server the runner starts sessions on.",
    )


class RoomConfig(BaseModel):
    """Room management configuration."""

    active: str | None = Field(
        default=None,
        description="Currently active room name",
    )


class ScrapeTarget(BaseModel):
    """A Prometheus ``/metrics`` endpoint for the collector to poll.

    Configured under ``[[metrics.scrape]]`` in ``config.toml``::

        [[metrics.scrape]]
        name = "my-service"
        url  = "http://localhost:9000/metrics"
        kind = "http_red"   # default; rolls up prometheus-fastapi-instrumentator series

    The collector polls every target on the same 30s cadence as the backend
    and stores results under the top-level ``scrape`` key in
    ``$MYCELIUM_DATA_DIR/metrics/metrics.json``. Targets unreachable at scrape time are
    preserved with ``data: null`` so the display panel can show "degraded"
    rather than silently dropping them.
    """

    name: str = Field(
        ...,
        description="Stable, short identifier used as the dict key in metrics.json and as the panel label.",
        min_length=1,
        max_length=64,
    )
    url: str = Field(
        ...,
        description="Full URL of the Prometheus exposition endpoint (typically ending in /metrics).",
    )
    kind: str = Field(
        default="http_red",
        description=(
            "Roll-up strategy: 'http_red' (HTTP rate/error/duration, e.g. "
            "prometheus-fastapi-instrumentator) or 'grpc_red' (gRPC RED, e.g. the "
            "OpenShell gateway's *_grpc_requests_total + *_grpc_request_duration_seconds)."
        ),
    )


class A2aConfig(BaseModel):
    """Configuration for the A2A bridge (outbound + inbound Agent2Agent gateway).

    The default settings are safe for a public-facing deployment: the SSRF guard
    refuses card URLs that resolve to private, loopback, or link-local addresses
    so a misconfigured or attacker-supplied card URL can't probe the internal
    network. Only set ``allow_private_hosts = true`` for a deployment where all
    A2A agents are on the internal network and you trust every registrar.
    """

    allow_private_hosts: bool = Field(
        default=False,
        description=(
            "Disable the SSRF guard that refuses A2A card URLs resolving to private, "
            "loopback, or link-local addresses. Only set this for a trusted internal "
            "deployment whose A2A agents live on the internal network."
        ),
    )


class AlignerConfig(BaseModel):
    """Hub settings still filed under ``[aligner]``, the engine that introduced them.

    The aligner itself was retired. The section keeps its name so an existing
    ``config.toml`` keeps working, and keys it no longer has (``term_check``,
    ``round_timeout_s``, ``max_steps``) are ignored when it loads.
    """

    handle: str = Field(
        default="aligner",
        description=(
            "A mention of this handle, in a room where no member has it, is answered "
            "with what to run now that the aligner is retired."
        ),
    )
    pi_timeout_s: float = Field(
        default=120.0,
        description="Seconds one model call by an engine can take.",
    )


class SynthesizerConfig(BaseModel):
    """What the synthesizer engine summarizes."""

    source: Literal["messages", "memory"] = Field(
        default="messages",
        description=(
            "messages: summarize the room's conversation since the last summary. "
            "memory: summarize every memory in the room each time."
        ),
    )


class WorkerConfig(BaseModel):
    """Limits on worker engines, the coding agents the hub runs."""

    tools: bool = Field(
        default=True,
        description=(
            "Let workers edit files and run commands. Off makes them write replies only, "
            "which is safer on a hub other people can use."
        ),
    )
    pi_timeout_s: float = Field(
        default=600.0,
        description="Seconds one worker request can take.",
    )
    max_turns_per_room: int = Field(
        default=60,
        description="Turns all workers in a room can take in total.",
    )


class VerifierConfig(BaseModel):
    """The verifier: checks what agents say about approvals and merges against the
    room's records, and adds a line under a message when a claim doesn't hold up."""

    enabled: bool = Field(
        default=False,
        description=(
            "Turn the verifier on for this hub. It then reads only the rooms that add it "
            "(`/engine verifier`, or Add member). Off, nothing is checked."
        ),
    )
    confirm: bool = Field(
        default=True,
        description=(
            "Have the hub's model read the thread before a line is shown, so a claim the "
            "records got wrong is dropped. It runs on a few messages in a hundred. Off, the "
            "records alone decide: cheaper, and noisier."
        ),
    )


class BoardConfig(BaseModel):
    """Board rules the hub enforces."""

    dependency_gate: bool = Field(
        default=False,
        description=(
            "Refuse a claim on a task that is still waiting on another task "
            "(depends-on). `board claim --force` claims it anyway."
        ),
    )


class UiConfig(BaseModel):
    """The web app (the UI server in front of the hub)."""

    public_host: str = Field(
        default="",
        description=(
            "The name the app is reached by besides this machine and its IP addresses, "
            "such as mycelium.example.com behind a proxy. The app refuses any other name, "
            "so a page that points its own name at this machine can't reach it."
        ),
    )


class VoiceConfig(BaseModel):
    """The message box's mic, transcribed on the hub, and notifications read aloud."""

    enabled: bool = Field(
        default=False,
        description=(
            "Let people talk into the message box. The hub transcribes on its own CPU, "
            "with a speech model of about 150 MB on disk, in a separate process that uses "
            "about 500 MB of memory while anyone is talking and exits a few minutes after. "
            "Off, the mic isn't offered and nothing is downloaded."
        ),
    )
    model: Literal["fast", "accurate"] = Field(
        default="fast",
        description=(
            "The speech model. fast is Moonshine: about 150 MB on disk and 500 MB of memory. "
            "accurate is Parakeet: about half the mistakes, at about 630 MB on disk (a 480 MB "
            "download, made the first time a mic is turned on) and 1.4 GB of memory. Both "
            "are English only. The hub reads it when it starts."
        ),
    )
    download: bool = Field(
        default=True,
        description=(
            "Let the hub download the speech model when voice is on and the model isn't "
            "there. Off, put the files in the hub's data folder under models/voice yourself."
        ),
    )
    speech_url: str = Field(
        default="",
        description=(
            "A speech server for reading notifications aloud: an OpenAI-style text-to-speech "
            "endpoint you run, such as http://127.0.0.1:8880/v1 (/audio/speech is added unless "
            "the address ends with it). The app asks the hub, and the hub asks this server, so "
            "it works from any page. Empty, the app doesn't offer to read notifications aloud. "
            "Mycelium ships no speech model. Independent of enabled, which is the mic."
        ),
    )
    speech_model: str = Field(
        default="",
        description="The model name the speech server expects. Empty sends none.",
    )
    speech_voice: str = Field(
        default="",
        description="The voice the speech server reads with. Empty sends none.",
    )
    speech_api_key: str = Field(
        default="",
        description="A key the speech server asks for, sent as a bearer token. Empty sends none.",
    )

    @field_validator("speech_url")
    @classmethod
    def validate_speech_url(cls, v: str) -> str:
        """An http(s) address or nothing, without a trailing slash."""
        v = v.strip().rstrip("/")
        if v and not v.lower().startswith(("http://", "https://")):
            msg = "voice.speech_url is an http:// or https:// address"
            raise ValueError(msg)
        return v


class PatternsConfig(BaseModel):
    """Design-pattern packs this hub offers (``/api/patterns``).

    A pattern is a scenario a caller loads as a room: a cast, some context, a
    task and the flow that sets them working. The hub offers only the pack its
    operator provides here and never fetches a location a caller names, so
    these settings are what a public hub tunes. They default to a private,
    trusting setup: no pack, scenarios accepted in the request, any member kind.
    """

    dir: str | None = Field(
        default=None,
        description=(
            "A folder holding scenarios/<pattern>/scenario.yaml, which the hub offers as its "
            "patterns. A path on this machine: in Docker it is mounted read-only into the "
            "backend. Unset means the hub offers none."
        ),
    )
    allow_inline: bool = Field(
        default=True,
        description=(
            "Let a caller send a scenario in the request (what `mycelium pattern use --from` "
            "does). Turn this off on a hub that should load only the patterns in its own pack."
        ),
    )
    personas_only: bool = Field(
        default=False,
        description=(
            "Refuse any scenario with a member that is not a persona or a person, so this hub "
            "never starts a worker (Pi with tools) for a caller."
        ),
    )


class TelemetryConfig(BaseModel):
    """Telemetry: the backend's OTel export, and whether the hub shares its usage stats.

    Two independent opt-ins kept deliberately separate:

    ``enabled`` activates the OpenTelemetry SDK in the backend: traces and
    metrics are exported over OTLP on every coordinated path (HTTP RED,
    engine runs, await long-poll). Off by default;
    never required for coordination or storage to work.

    ``send_product_analytics`` shares the hub's usage events. The hub records
    them either way (tasks filed and resolved, flows and negotiations finished,
    agents joined, the hub starting) and the app's Metrics page reads them;
    this sends the same events to ``analytics_destination``. Off by default,
    asked at interactive install and on the desktop app's first-run screen. No
    names, handles, rooms, task text, prompts or replies are ever included.
    """

    enabled: bool = Field(
        default=False,
        description=(
            "Enable the OTel SDK in the backend (traces + metrics exported to the OTLP "
            "collector). Off by default."
        ),
    )
    otlp_endpoint: str | None = Field(
        default=None,
        description=(
            "OTLP HTTP endpoint the backend pushes spans and metrics to. "
            "When unset and telemetry.enabled is true, defaults to "
            "http://mycelium-collector:4318, the collector's address in the Docker stack. "
            "The desktop app runs no collector, so set this there (for example "
            "http://127.0.0.1:4318 for a collector on the same machine)."
        ),
    )
    otlp_headers: str | None = Field(
        default=None,
        description=(
            "Headers sent with every OTLP export, such as a hosted backend's auth "
            '(for example "x-honeycomb-team=<key>"). Also used by the local Grafana '
            "when it forwards. Rendered as OTEL_EXPORTER_OTLP_HEADERS."
        ),
    )
    forward_endpoint: str | None = Field(
        default=None,
        description=(
            "With the local Grafana (`mycelium up --grafana`), also forward everything it "
            "receives to this OTLP endpoint. Rendered as OTEL_EXPORTER_OTLP_ENDPOINT."
        ),
    )
    send_product_analytics: bool = Field(
        default=False,
        description=(
            "Share the hub's anonymous usage events (tasks filed and resolved, flows and "
            "negotiations finished, agents joined) with the analytics destination. The hub "
            "records them either way. Off by default; the desktop app's own setting wins there."
        ),
    )
    analytics_destination: str | None = Field(
        default=None,
        description=(
            "Where shared usage events are POSTed, as JSON (or Loki's push format for a "
            "/loki/ URL). HTTPS, or plain HTTP to this machine only."
        ),
    )
    install_id: str | None = Field(
        default=None,
        description=(
            "Random UUID identifying this installation, generated on first interactive "
            "`mycelium install`; a hub without one mints its own. Carried on usage events, "
            "and sent nowhere unless the hub shares them."
        ),
    )


class HealthConfig(BaseModel):
    """Health degradation thresholds for ``GET /health`` (#453).

    When a histogram's p95 exceeds its threshold, ``/health`` reports
    ``status: degraded`` for that subsystem. Set any threshold to ``0`` to
    disable that check.
    """

    llm_p95_threshold_ms: float = Field(
        default=30000.0,
        description="LLM call p95 above this value degrades /health (0 = disabled).",
    )
    await_p95_threshold_ms: float = Field(
        default=60000.0,
        description=(
            "Delivered-await p95 above this value degrades /health (0 = disabled). "
            "Timed-out long-polls are excluded."
        ),
    )
    search_p95_threshold_ms: float = Field(
        default=500.0,
        description="Memory search p95 above this value degrades /health (0 = disabled).",
    )


class MetricsConfig(BaseModel):
    """Configuration for the metrics collector + display.

    Use ``[[metrics.scrape]]`` to add Prometheus ``/metrics`` targets (e.g. a
    user's own instrumented service) for the collector to poll.

    On spoke nodes, set ``collector_url`` to the hub's collector address
    (e.g. ``http://hub-ip:4318``). This makes ``mycelium metrics show``
    fetch data from the hub and sets the default OTLP endpoint for
    adapter plugins; no local collector needed.
    """

    collector_url: str | None = Field(
        default=None,
        description=(
            "URL of the hub OTLP collector (e.g. http://hub-ip:4318). "
            "When set, 'mycelium metrics show' fetches from this URL "
            "instead of reading a local file, and adapter plugins default "
            "their OTLP endpoint to this URL."
        ),
    )
    scrape: list[ScrapeTarget] = Field(
        default_factory=list,
        description="Explicit Prometheus /metrics endpoints for the collector to scrape.",
    )


#: The shortest a widget's command may wait between runs.
WIDGET_MIN_EVERY_S = 5
#: A widget's ``every`` for a command kept running while the app is open.
WIDGET_ALWAYS = "always"
#: The theme colors a widget can be drawn in, by name, so every theme still reads.
WIDGET_COLORS = ("accent", "green", "yellow", "red", "muted")
#: The states a widget's dot can show (the app's own ``StatusDot``).
WIDGET_STATES = ("ok", "warn", "bad", "off")
#: How much of a tooltip a widget keeps: a few lines, not a page.
WIDGET_TOOLTIP_LINES = 8
WIDGET_TOOLTIP_CHARS = 1000
#: The fields that set how a widget looks, from its config or from a run's JSON.
WIDGET_LOOK = ("icon", "color", "state", "meter", "tooltip")

_ICON_NAME = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")


def _is_emoji(value: str) -> bool:
    """One emoji, as far as a check here can tell: short, no letters, no spaces.
    The app draws it as text, so a near miss shows as what was written."""
    return (
        0 < len(value) <= 8
        and value.isprintable()
        and not any(c.isascii() or c.isspace() for c in value)
    )


def widget_look(raw: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    """The fields in ``raw`` that set how a widget looks and are good, and a
    note for each that isn't. A bad field is left out, never the widget.

    ``icon`` is a Lucide icon's kebab-case name (the app falls back to its
    default for a name it doesn't know) or one emoji; ``color`` and ``state``
    are names from :data:`WIDGET_COLORS` and :data:`WIDGET_STATES`; ``meter``
    is a number from 0 to 100; ``tooltip`` is a few lines of markdown.
    """
    good: dict[str, Any] = {}
    notes: list[str] = []
    for field in WIDGET_LOOK:
        if raw.get(field) is None:
            continue
        value = raw[field]
        if field == "icon":
            ok = isinstance(value, str) and (bool(_ICON_NAME.match(value)) or _is_emoji(value))
            hint = "a Lucide icon name like memory-stick, or one emoji"
        elif field == "color":
            ok = value in WIDGET_COLORS
            hint = f"one of {', '.join(WIDGET_COLORS)}"
        elif field == "state":
            ok = value in WIDGET_STATES
            hint = f"one of {', '.join(WIDGET_STATES)}"
        elif field == "meter":
            ok = (
                isinstance(value, int | float) and not isinstance(value, bool) and 0 <= value <= 100
            )
            value = float(value) if ok else value
            hint = "a number from 0 to 100"
        else:
            ok = isinstance(value, str)
            if ok:
                lines = value.strip().splitlines()[:WIDGET_TOOLTIP_LINES]
                value = "\n".join(lines)[:WIDGET_TOOLTIP_CHARS]
            hint = "text"
        if ok:
            good[field] = value
        else:
            notes.append(f"{field} {str(value)[:40]!r} was ignored: it should be {hint}.")
    return good, notes


class StatusWidget(BaseModel):
    """One row of the desktop app's Widgets card, under ``[[statusline.widget]]``::

        [[statusline.widget]]
        label = "RAM"
        command = "~/bin/ram.sh"
        every = "30s"
        icon = "memory-stick"
        color = "accent"

    Either ``command`` (run by the desktop app on this computer, every
    ``every``) or ``text`` (fixed words). A command shows the first line it
    prints, or, when what it prints is one JSON object, sets its fields for
    that run: ``text`` and the look fields (:func:`widget_look`), over the
    config's. ``every = "always"`` keeps the command running while the app is
    open instead, and shows the last line it printed. Text is inline markdown. A look field that's wrong is left out
    with a note (``notes``), never stopping the widget or its other fields.
    """

    label: str = Field(..., min_length=1, max_length=64, description="What the row is called.")
    command: str | None = Field(
        default=None, description="A shell command the desktop app runs on this computer."
    )
    text: str | None = Field(default=None, description="Fixed words to show instead of a command.")
    every: str = Field(
        default="1m",
        pattern=r"^(\d+\s*[smh]|always)$",
        description=(
            "How often the command runs: seconds, minutes or hours, e.g. '30s', '5m'. "
            "Or 'always': it runs the whole time the app is open, and is started "
            "again when it stops."
        ),
    )
    timeout: float = Field(
        default=10.0,
        gt=0,
        le=600,
        description="Seconds before a run counts as hung. Not used with every = 'always'.",
    )
    icon: str | None = Field(
        default=None, description="A Lucide icon's kebab-case name, or one emoji."
    )
    color: str | None = Field(
        default=None, description=f"A theme color by name: {', '.join(WIDGET_COLORS)}."
    )
    state: str | None = Field(
        default=None, description=f"A status dot: {', '.join(WIDGET_STATES)}."
    )
    meter: bool | float | None = Field(
        default=None,
        description=(
            "A bar under the row: a number from 0 to 100, or true to read a "
            "percentage from the text."
        ),
    )
    tooltip: str | None = Field(
        default=None, description="Markdown shown under the command on hover."
    )
    #: Why a look field was left out, for Settings. Not set by the person.
    notes: list[str] = Field(default_factory=list)

    @model_validator(mode="before")
    @classmethod
    def _keep_good_look(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        rest = {k: v for k, v in data.items() if k not in (*WIDGET_LOOK, "notes")}
        # `meter = true` still means "read a percentage from the text"; false, none.
        legacy = data.get("meter") if isinstance(data.get("meter"), bool) else None
        good, notes = widget_look({k: v for k, v in data.items() if k != "meter" or legacy is None})
        if legacy:
            good["meter"] = True
        return rest | good | {"notes": notes}

    @model_validator(mode="after")
    def _one_source(self) -> "StatusWidget":
        if (self.command is None) == (self.text is None):
            raise ValueError(f"widget {self.label!r} needs exactly one of 'command' or 'text'")
        if not self.always() and self.seconds() < WIDGET_MIN_EVERY_S:
            raise ValueError(
                f"widget {self.label!r}: every must be at least {WIDGET_MIN_EVERY_S}s, "
                f"not {self.every!r}"
            )
        return self

    def always(self) -> bool:
        """Whether the command is kept running rather than run on an interval."""
        return self.every == WIDGET_ALWAYS

    def seconds(self) -> float:
        """``every`` in seconds (not for a widget kept running, :meth:`always`)."""
        n, unit = int(self.every[:-1].strip()), self.every[-1]
        return float(n * {"s": 1, "m": 60, "h": 3600}[unit])


class StatuslineConfig(BaseModel):
    """The rows of the desktop app's Widgets card, as the desktop app reads them.

    Validated only by the desktop app (``desktop/widgets.py``), which shows a
    bad widget's error in Settings and runs none of them. ``MyceliumConfig``
    holds this section unvalidated (:class:`StatuslineSection`), so a typo in a
    status readout never stops a ``mycelium`` command."""

    widget: list[StatusWidget] = Field(
        default_factory=list, description="The rows of the Widgets card, in order."
    )


class StatuslineSection(BaseModel):
    """The desktop app's Widgets card, read and run on this computer only."""

    # ``Any``, not a list of tables: even a section of the wrong shape is the
    # desktop app's to report, never a reason for the CLI to stop.
    widget: Any = Field(
        default=[],
        description=(
            "The rows of the Widgets card, in order, as [[statusline.widget]] tables: "
            "label, then command (with every, timeout) or text, and optionally icon "
            "(a Lucide icon name like memory-stick, or one emoji), color (accent, green, "
            "yellow, red, muted), state (ok, warn, bad, off), meter (0 to 100) and "
            "tooltip. Text and tooltip are inline markdown: **bold**, *italic*, `code`. "
            "A command can print one JSON object instead of a line to set any of these "
            'for that run, e.g. {"text": "**38%** free", "icon": "memory-stick", '
            '"state": "warn", "meter": 38, "tooltip": "Swap is *2.1G*"}. Checked by '
            "the desktop app, which notes any field it ignored in Settings > Widgets. "
            'every = "always" keeps a command running while the app is open, and its '
            "row shows whether it's running. Every command gets the port of the hub "
            "the app runs as $MYCELIUM_HUB_PORT."
        ),
    )

    @model_validator(mode="before")
    @classmethod
    def _any_shape(cls, data: Any) -> Any:
        """``statusline = "x"`` is kept as it was written, for the app to report."""
        return data if isinstance(data, dict) else {"widget": data}


class MyceliumConfig(BaseModel):
    """Complete Mycelium CLI configuration."""

    identity: IdentityConfig = Field(default_factory=IdentityConfig)
    server: ServerConfig = Field(default_factory=ServerConfig)
    llm: LLMConfig = Field(default_factory=LLMConfig)
    engine: EngineConfig = Field(default_factory=EngineConfig)
    aligner: AlignerConfig = Field(default_factory=AlignerConfig)
    synthesizer: SynthesizerConfig = Field(default_factory=SynthesizerConfig)
    worker: WorkerConfig = Field(default_factory=WorkerConfig)
    board: BoardConfig = Field(default_factory=BoardConfig)
    ui: UiConfig = Field(default_factory=UiConfig)
    voice: VoiceConfig = Field(default_factory=VoiceConfig)
    verifier: VerifierConfig = Field(default_factory=VerifierConfig)
    auth: AuthConfig = Field(default_factory=AuthConfig)
    login: LoginConfig = Field(default_factory=LoginConfig)
    agent_auth: AgentAuthConfig = Field(default_factory=AgentAuthConfig)
    runtime: RuntimeConfig = Field(default_factory=RuntimeConfig)
    herdr: HerdrConfig = Field(default_factory=HerdrConfig)
    runner: RunnerConfig = Field(default_factory=RunnerConfig)
    rooms: RoomConfig = Field(default_factory=RoomConfig)
    metrics: MetricsConfig = Field(default_factory=MetricsConfig)
    telemetry: TelemetryConfig = Field(default_factory=TelemetryConfig)
    health: HealthConfig = Field(default_factory=HealthConfig)
    a2a: A2aConfig = Field(default_factory=A2aConfig)
    patterns: PatternsConfig = Field(default_factory=PatternsConfig)
    statusline: StatuslineSection = Field(default_factory=StatuslineSection)

    model_config = {"arbitrary_types_allowed": True}
    _global_config_path: Path | None = None
    _project_config_path: Path | None = None
    #: (section, key) -> (what the files said, what a joined folder's membership
    #: put there). A membership belongs to its folder, so save() writes the
    #: files' value back unless the key was changed after loading.
    _membership_overrides: dict[tuple[str, str], tuple[Any, Any]] = {}  # noqa: RUF012 - per-instance, set by load()
    #: The ``identity`` sections the global and the project file had when loaded.
    #: A folder's config keeps only the identity keys it set itself, so the
    #: machine's identity is never copied into it to shadow ~/.mycelium for every
    #: folder below.
    _global_identity: dict[str, Any] = {}  # noqa: RUF012 - per-instance, set by load()
    _project_identity: dict[str, Any] = {}  # noqa: RUF012 - per-instance, set by load()

    #: Sections that live only in a project's .mycelium/config.toml.
    PROJECT_ONLY_SECTIONS: ClassVar[frozenset[str]] = frozenset({"rooms"})

    @classmethod
    def get_global_config_dir(cls) -> Path:
        return Path.home() / ".mycelium"

    @classmethod
    def get_agent_state_dir(cls) -> Path:
        """What the CLI writes when an agent runs it: ``await``'s pending
        confirmations and minted agent tokens, and nothing else.

        Kept apart from the rest of ``~/.mycelium`` so a sandboxed agent (Codex)
        can be given this folder alone, never the config, the herdr registry or
        the runner's approval files beside it.
        """
        return cls.get_global_config_dir() / "agent-state"

    @classmethod
    def get_global_config_path(cls) -> Path:
        return cls.get_global_config_dir() / "config.toml"

    @classmethod
    def get_logs_dir(cls) -> Path:
        logs_dir = cls.get_global_config_dir() / "logs"
        logs_dir.mkdir(parents=True, exist_ok=True)
        return logs_dir

    @classmethod
    def get_project_config_dir(cls) -> Path:
        return Path.cwd() / ".mycelium"

    @classmethod
    def get_project_config_path(cls) -> Path:
        return cls.get_project_config_dir() / "config.toml"

    @classmethod
    def find_project_config(cls) -> Path | None:
        """Find project-local .mycelium/ by walking up directory tree."""
        global_dir = cls.get_global_config_dir()
        current = Path.cwd()
        while current != current.parent:
            config_path = current / ".mycelium" / "config.toml"
            if config_path.exists() and config_path.parent != global_dir:
                return config_path
            current = current.parent
        return None

    @classmethod
    def has_project_config(cls) -> bool:
        return cls.find_project_config() is not None

    @classmethod
    def get_config_path(cls) -> Path:
        project_config = cls.find_project_config()
        return project_config if project_config else cls.get_global_config_path()

    @classmethod
    def get_config_dir(cls) -> Path:
        project_config = cls.find_project_config()
        if project_config:
            return project_config.parent
        return cls.get_global_config_dir()

    @classmethod
    def load(cls, config_path: Path | None = None) -> "MyceliumConfig":
        """Load configuration from global and project-local files."""
        config_dict: dict[str, Any] = {}
        replaced: dict[tuple[str, str], tuple[Any, Any]] = {}
        global_identity: dict[str, Any] = {}
        project_identity: dict[str, Any] = {}

        if config_path is not None:
            if config_path.exists():
                with open(config_path) as f:
                    config_dict = toml.load(f)
            global_path = config_path
            project_path = None
        else:
            global_path = cls.get_global_config_path()
            if global_path.exists():
                with open(global_path) as f:
                    config_dict = toml.load(f)
            global_identity = dict(config_dict.get("identity") or {})

            project_path = cls.find_project_config()
            if project_path and project_path.exists():
                with open(project_path) as f:
                    project_dict = toml.load(f)
                project_identity = dict(project_dict.get("identity") or {})
                config_dict = cls._deep_merge(config_dict, project_dict)

            # A folder that joined a room (`mycelium join`) names its hub and
            # room; that beats this machine's files and loses to the environment.
            # With no membership, the desktop app's client-mode hub stands in
            # when the files name no hub of their own.
            from mycelium import caller

            overlay = caller.config_overlay(config_dict.get("server", {}).get("api_url"))
            replaced = {
                (section, key): (config_dict.get(section, {}).get(key), value)
                for section, keys in overlay.items()
                for key, value in keys.items()
            }
            config_dict = cls._deep_merge(config_dict, overlay)

        env_overrides = cls._load_from_env()
        config_dict = cls._deep_merge(config_dict, env_overrides)

        instance = cls(**config_dict)
        instance._global_config_path = global_path
        instance._project_config_path = project_path
        instance._membership_overrides = replaced
        instance._global_identity = global_identity
        instance._project_identity = project_identity
        return instance

    @classmethod
    def _load_from_env(cls) -> dict[str, Any]:
        """Load configuration overrides from environment variables."""
        env_config: dict[str, Any] = {
            "server": {},
            "rooms": {},
            "llm": {},
            "engine": {},
            "login": {},
            "agent_auth": {},
            "runtime": {},
            "metrics": {},
            "telemetry": {},
            "health": {},
        }

        if engine_runtime := os.getenv("ENGINE_RUNTIME"):
            env_config["engine"]["runtime"] = engine_runtime

        if api_url := os.getenv("MYCELIUM_API_URL"):
            from mycelium.caller import follow_app_hub

            # An agent's address for the app's hub, from before the app restarted.
            env_config["server"]["api_url"] = follow_app_hub(api_url)
        if active_room := os.getenv("MYCELIUM_ACTIVE_ROOM"):
            env_config["rooms"]["active"] = active_room

        # LLM overrides
        if llm_model := os.getenv("LLM_MODEL"):
            env_config["llm"]["model"] = llm_model
        if llm_api_key := os.getenv("LLM_API_KEY"):
            env_config["llm"]["api_key"] = llm_api_key
        if llm_base_url := os.getenv("LLM_BASE_URL"):
            env_config["llm"]["base_url"] = llm_base_url

        # Login (OIDC client) overrides: how a CI runner points `mycelium login`
        # at an issuer without writing a config file.
        if login_issuer := os.getenv("MYCELIUM_LOGIN_ISSUER"):
            env_config["login"]["issuer"] = login_issuer
        if login_client_id := os.getenv("MYCELIUM_LOGIN_CLIENT_ID"):
            env_config["login"]["client_id"] = login_client_id
        if login_client_secret := os.getenv("MYCELIUM_LOGIN_CLIENT_SECRET"):
            env_config["login"]["client_secret"] = login_client_secret
        if login_audience := os.getenv("MYCELIUM_LOGIN_AUDIENCE"):
            env_config["login"]["audience"] = login_audience
        if login_scopes := os.getenv("MYCELIUM_LOGIN_SCOPES"):
            env_config["login"]["scopes"] = login_scopes

        # Agent (service-account) overrides: how a container hands its agent an
        # issuer without a config file. The per-agent client id and secret are
        # secrets and stay out of config; see `mycelium.agent_credentials`.
        if agent_issuer := os.getenv("MYCELIUM_AGENT_AUTH_ISSUER"):
            env_config["agent_auth"]["issuer"] = agent_issuer
        if agent_scopes := os.getenv("MYCELIUM_AGENT_AUTH_SCOPES"):
            env_config["agent_auth"]["scopes"] = agent_scopes
        if agent_audience := os.getenv("MYCELIUM_AGENT_AUTH_AUDIENCE"):
            env_config["agent_auth"]["audience"] = agent_audience

        # Metrics overrides
        if collector_url := os.getenv("MYCELIUM_COLLECTOR_URL"):
            env_config["metrics"]["collector_url"] = collector_url

        # Telemetry overrides
        if val := os.getenv("MYCELIUM_TELEMETRY_ENABLED"):
            env_config["telemetry"]["enabled"] = val.lower() in ("1", "true", "yes")
        if val := os.getenv("MYCELIUM_TELEMETRY_OTLP_ENDPOINT"):
            env_config["telemetry"]["otlp_endpoint"] = val
        if val := os.getenv("MYCELIUM_TELEMETRY_SEND_ANALYTICS"):
            env_config["telemetry"]["send_product_analytics"] = val.lower() in ("1", "true", "yes")
        if val := os.getenv("MYCELIUM_ANALYTICS_DESTINATION"):
            env_config["telemetry"]["analytics_destination"] = val

        # Health degradation thresholds
        if val := os.getenv("HEALTH_LLM_P95_THRESHOLD_MS"):
            env_config["health"]["llm_p95_threshold_ms"] = float(val)
        if val := os.getenv("HEALTH_AWAIT_P95_THRESHOLD_MS"):
            env_config["health"]["await_p95_threshold_ms"] = float(val)
        if val := os.getenv("HEALTH_SEARCH_P95_THRESHOLD_MS"):
            env_config["health"]["search_p95_threshold_ms"] = float(val)

        return env_config

    @classmethod
    def _deep_merge(cls, base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
        """Deep merge two dictionaries."""
        result = base.copy()
        for key, value in override.items():
            if key in result and isinstance(result[key], dict) and isinstance(value, dict):
                result[key] = cls._deep_merge(result[key], value)
            elif value is not None:
                result[key] = value
        return result

    def resolve_scrape_targets(self) -> list[dict]:
        """Return the list of Prometheus scrape targets for the collector.

        Targets are the explicit ``[[metrics.scrape]]`` entries declared in
        ``config.toml`` (e.g. a user's own Prometheus-instrumented service).
        """
        derived: dict[str, dict] = {}
        for explicit in self.metrics.scrape:
            derived[explicit.name] = explicit.model_dump()

        return list(derived.values())

    def save(self, config_path: Path | None = None) -> None:
        """Save configuration to appropriate files and write JSON snapshot for JS consumers."""
        config_dict = self.model_dump(mode="json", exclude_none=True)
        # A joined folder's hub and room are the folder's, not this machine's:
        # write back what the files said unless the key was changed since.
        for (section, key), (from_files, from_membership) in self._membership_overrides.items():
            current = config_dict.get(section, {})
            if current.get(key) == from_membership:
                if from_files is None:
                    current.pop(key, None)
                else:
                    current[key] = from_files

        if config_path is not None:
            config_path.parent.mkdir(parents=True, exist_ok=True)
            with open(config_path, "w") as f:
                toml.dump(config_dict, f)
            # Holds secrets (llm.api_key); keep it owner-only.
            config_path.chmod(0o600)
            self._write_json_snapshot(config_path.parent)
            return

        global_path = self._global_config_path or self.get_global_config_path()
        global_path.parent.mkdir(parents=True, exist_ok=True)

        # Every section is global except the project-only ones. Derived from the
        # model, not listed, so a new section is saved without anyone
        # remembering to add it here (runner.host was once set and dropped).
        _global_sections = set(type(self).model_fields) - self.PROJECT_ONLY_SECTIONS

        if self._project_config_path:
            global_dict = {k: v for k, v in config_dict.items() if k in _global_sections}
            project_dict = {k: v for k, v in config_dict.items() if k in self.PROJECT_ONLY_SECTIONS}
            # identity is the machine's, except the keys the folder set itself:
            # those stay the folder's, and the machine keeps its own values.
            identity = config_dict.get("identity", {})
            owned = set(self._project_identity)
            if folder_identity := {k: identity[k] for k in owned if k in identity}:
                project_dict["identity"] = folder_identity
            global_dict["identity"] = {
                **{k: v for k, v in identity.items() if k not in owned},
                **{k: v for k, v in self._global_identity.items() if k in owned},
            }
            with open(self._project_config_path, "w") as f:
                toml.dump(project_dict, f)
        else:
            global_dict = config_dict

        with open(global_path, "w") as f:
            toml.dump(global_dict, f)
        # Holds secrets (llm.api_key); keep it owner-only.
        global_path.chmod(0o600)
        self._write_json_snapshot(global_path.parent)

    def _write_json_snapshot(self, config_dir: Path) -> None:
        """Write a config.json snapshot for JS/TS consumers.

        Regenerated from config.toml on every save; edits to config.json are
        silently discarded. We prepend a ``"//"`` header key (the npm/
        package.json convention for in-JSON comments) so anyone opening the
        file sees the warning at the top. See _JSON_HEADER_* for why this
        key name is safe across consumers.
        """
        import json

        snapshot = {
            _JSON_HEADER_KEY: _JSON_HEADER_VALUE,
            **self.model_dump(mode="json", exclude_none=True),
        }
        json_path = config_dir / "config.json"
        with open(json_path, "w", encoding="utf-8") as f:
            # ensure_ascii=False so the header's em-dashes stay readable on `cat`
            # rather than showing as `\u2014`.
            json.dump(snapshot, f, indent=2, ensure_ascii=False)
            f.write("\n")
        # The snapshot is a full config dump (includes llm.api_key); keep it
        # owner-only, same as config.toml.
        json_path.chmod(0o600)

    def get_data_dir(self) -> Path:
        if self.runtime.data_dir:
            return Path(self.runtime.data_dir).expanduser()
        return self.get_global_config_dir()

    def save_to_project(self, project_dir: Path | None = None) -> None:
        """Save room settings to project-local .mycelium/."""
        if project_dir is None:
            project_dir = Path.cwd()

        config_dir = project_dir / ".mycelium"
        config_path = config_dir / "config.toml"
        config_dir.mkdir(parents=True, exist_ok=True)

        config_dict = self.model_dump(mode="json", exclude_none=True)
        project_dict = {k: v for k, v in config_dict.items() if k == "rooms"}
        # Like save(): only the identity keys this folder's file already set.
        existing: dict[str, Any] = {}
        if config_path.exists():
            with open(config_path) as f:
                existing = toml.load(f)
        identity = config_dict.get("identity", {})
        if folder_identity := {
            k: identity[k] for k in existing.get("identity") or {} if k in identity
        }:
            project_dict["identity"] = folder_identity

        with open(config_path, "w") as f:
            toml.dump(project_dict, f)

        self._project_config_path = config_path

    def init_project(self, project_dir: Path | None = None, room_name: str | None = None) -> Path:
        """Initialize a project-local .mycelium/ directory."""
        if project_dir is None:
            existing = self.find_project_config()
            if existing:
                project_dir = existing.parent.parent
            else:
                project_dir = Path.cwd()

        config_dir = project_dir / ".mycelium"
        config_dir.mkdir(parents=True, exist_ok=True)

        if room_name:
            self.rooms.active = room_name

        self.save_to_project(project_dir)
        return config_dir

    def identity_name_path(self) -> Path | None:
        """The file ``identity.name`` was read from, or ``None`` when no file set it."""
        if "name" in self._project_identity:
            return self._project_config_path
        if "name" in self._global_identity:
            return self._global_config_path
        return None

    def get_active_room(self) -> str | None:
        return self.rooms.active

    def set_active_room(self, room_name: str) -> None:
        """Set the active room and save configuration."""
        self.rooms.active = room_name
        self.save()

    def clear_active_room(self) -> None:
        self.rooms.active = None
        self.save()

    def get_current_identity(self) -> str:
        """This machine's acting identity, for a sender handle.

        A thin wrapper over the one resolver (:func:`mycelium.identity.resolve_actor`)
        so a sender and a write's author are found the same way: an explicit
        override the caller passes, then ``MYCELIUM_AGENT_HANDLE``, then the hub's
        own view of our token, then local ``iam`` config, then ``"unknown"``.
        ``require=False`` because a sender read must not raise — the caller decides
        what an unresolved sender means.
        """
        from mycelium.identity import resolve_actor

        return resolve_actor(self, require=False, fallback="unknown")
