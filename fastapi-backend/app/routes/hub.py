# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""Hub API: what this hub is set up with, for the people who use it.

GET   /hub/settings   the model its agents use, its experiences, whether it
                      shares usage stats, what workers may do, sign-in, voice
                      and the verifier, and whether this caller may change them
PATCH /hub/settings   save settings to config.toml (``services/hub_config.py``)
POST  /hub/restart    restart a desktop hub so saved settings apply

A hub is often a server nobody using it can reach the configuration of. For
them it is read-only, and it never says a key or an endpoint, only whether one
is set. Someone who may change it (a desktop hub, or a person when sign-in is
on) also gets each setting's value, and never a key. Settings live where they
always have (``config.toml`` on the hub's machine).
"""

from __future__ import annotations

import asyncio
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from app.config import settings
from app.services import hub_config, patterns

router = APIRouter(prefix="/hub", tags=["hub"])


class HubModel(BaseModel):
    model: str | None = Field(None, description="provider/model, as the hub runs it")
    provider: str | None = Field(None, description="The part of the model name before the slash")
    has_key: bool = Field(description="Whether an API key is set; the key itself is never shown")
    custom_endpoint: bool = Field(description="Whether it answers at an address set by hand")


class HubExperience(BaseModel):
    id: str
    title: str
    description: str
    open: str = Field(description="Where it opens in the hub's UI")
    unit: str = Field(description="What one of its scenarios is called")
    scenarios: int = Field(description="How many scenarios it has")


class HubWorkers(BaseModel):
    tools: bool = Field(description="Workers can run commands in their checkout")
    turn_timeout_s: float = Field(description="The longest one worker turn may take")
    max_turns_per_room: int = Field(description="Worker turns a room gets; a room may lower it")


class HubVoice(BaseModel):
    enabled: bool = Field(description="The hub transcribes the message box's mic")
    model: str = Field(description="fast or accurate")


class HubEditing(BaseModel):
    """Whether this caller may change the hub's settings from the page, and how."""

    may_edit: bool
    reason: str | None = Field(None, description="Why not, when it may not")
    can_restart: bool = Field(description="The hub can restart itself to apply changes")
    app_owned: list[str] = Field(
        default_factory=list,
        description="Keys the desktop app sets itself; changed in the app's own settings",
    )
    pending: list[str] = Field(
        default_factory=list,
        description="Keys saved since the hub started: they apply at its next start",
    )
    values: dict[str, Any] = Field(
        default_factory=dict,
        description=(
            "What each editable key is set to, saved changes included, for an editor"
            " only. A key is sent only as whether it is set."
        ),
    )


class HubSettings(BaseModel):
    """What this hub is set up with, and whether this caller may change it."""

    model: HubModel
    experiences: list[HubExperience]
    personas_only: bool = Field(description="Patterns may start personas only, never workers")
    share_usage: bool = Field(description="Whether this hub sends its anonymous usage stats")
    workers: HubWorkers
    dependency_gate: bool = Field(
        description="A row waiting on another can't be claimed, unless a room sets otherwise"
    )
    patterns_inline: bool = Field(description="A caller may send a scenario in the request")
    sign_in: bool = Field(description="Callers must present a token")
    voice: HubVoice
    verifier: bool = Field(False, description="The verifier is on for this hub")
    editing: HubEditing


class HubSettingsChange(BaseModel):
    """Settings to save, by config key (``contracts/hub-settings.json``). An empty
    text or key clears it."""

    changes: dict[str, Any] = Field(..., min_length=1)


class HubSettingsSaved(BaseModel):
    saved: list[str]
    pending: list[str] = Field(description="Everything saved since the hub started")
    restart_needed: bool = Field(True, description="Saved settings apply when the hub next starts")


#: The experiences Mycelium knows. Frozen in ``contracts/experiences.json``,
#: which the CLI's catalogue (``mycelium/desktop/experiences.py``) also matches;
#: the image carries only this package, so this is a checked copy of it.
EXPERIENCES: list[dict[str, str]] = [
    {
        "id": "patterns-explorer",
        "title": "Patterns Explorer",
        "description": "Watch a team of agents work through a business scenario, start to finish.",
        "open": "/patterns",
        "unit": "business scenario",
    },
]


def _scenarios(experience_id: str) -> int:
    """How many scenarios this hub has for an experience; 0 when it has none."""
    if experience_id == "patterns-explorer":
        return len(patterns.pack_names())
    return 0


def _values() -> dict[str, Any]:
    """Each editable key's value as this hub runs it; a key only as set or not."""
    return {
        "llm.model": settings.LLM_MODEL or "",
        "llm.base_url": settings.LLM_BASE_URL or "",
        "llm.api_key": bool((settings.LLM_API_KEY or "").strip()),
        "verifier.enabled": settings.VERIFIER_ENABLED,
        "voice.enabled": settings.VOICE_ENABLED,
        "voice.model": settings.VOICE_MODEL,
        "telemetry.send_product_analytics": settings.TELEMETRY_SEND_PRODUCT_ANALYTICS,
        "worker.tools": settings.WORKER_TOOLS,
        "worker.pi_timeout_s": settings.WORKER_PI_TIMEOUT_S,
        "worker.max_turns_per_room": settings.WORKER_MAX_TURNS_PER_ROOM,
        "board.dependency_gate": settings.BOARD_DEPENDENCY_GATE,
    }


def _editing(request: Request) -> HubEditing:
    access = hub_config.access(request)
    return HubEditing(
        may_edit=access.may_edit,
        reason=access.reason,
        can_restart=access.may_edit and access.can_restart,
        app_owned=access.app_owned,
        pending=hub_config.pending(),
        values={**_values(), **hub_config.saved()} if access.may_edit else {},
    )


@router.patch("/settings", response_model=HubSettingsSaved)
async def change_hub_settings(payload: HubSettingsChange, request: Request) -> HubSettingsSaved:
    """Save settings to config.toml through the CLI. They apply at the hub's next start."""
    access = hub_config.access(request)
    if not access.may_edit:
        raise HTTPException(status_code=403, detail=access.reason or "Can't change this hub here")
    try:
        saved = await asyncio.to_thread(hub_config.write, payload.changes, access.app_owned)
    except hub_config.HubConfigError as err:
        raise HTTPException(status_code=err.status, detail=err.detail) from err
    return HubSettingsSaved(saved=saved, pending=hub_config.pending())


@router.post("/restart", status_code=202)
async def restart_hub(request: Request) -> dict[str, str]:
    """Restart this hub so saved settings apply. A desktop hub only: its
    supervisor starts it again. Answers before it goes."""
    access = hub_config.access(request)
    if not access.may_edit:
        raise HTTPException(status_code=403, detail=access.reason or "Can't restart this hub here")
    if not access.can_restart:
        raise HTTPException(
            status_code=409,
            detail="This hub can't restart itself. Restart it on its machine.",
        )
    # After this answer is on its way.
    asyncio.get_running_loop().call_later(0.3, hub_config.request_restart)
    return {"status": "restarting"}


@router.get("/settings", response_model=HubSettings)
async def hub_settings(request: Request) -> HubSettings:
    """What this hub is set up with, without a key or an address in it unless the
    caller may change it (and never a key)."""
    model = (settings.LLM_MODEL or "").strip() or None
    experiences = [
        HubExperience(**x, scenarios=n) for x in EXPERIENCES if (n := _scenarios(x["id"]))
    ]
    return HubSettings(
        model=HubModel(
            model=model,
            provider=model.split("/", 1)[0] if model and "/" in model else None,
            has_key=bool((settings.LLM_API_KEY or "").strip()),
            custom_endpoint=bool(settings.LLM_BASE_URL),
        ),
        experiences=experiences,
        personas_only=settings.PATTERNS_PERSONAS_ONLY,
        share_usage=settings.TELEMETRY_SEND_PRODUCT_ANALYTICS,
        workers=HubWorkers(
            # As worker_engine.tooled() decides it: the sandbox can't see the checkout.
            tools=settings.WORKER_TOOLS and not settings.ALIGNER_PI_OPENSHELL,
            turn_timeout_s=settings.WORKER_PI_TIMEOUT_S,
            max_turns_per_room=settings.WORKER_MAX_TURNS_PER_ROOM,
        ),
        dependency_gate=settings.BOARD_DEPENDENCY_GATE,
        patterns_inline=settings.PATTERNS_ALLOW_INLINE,
        sign_in=settings.AUTH_ENABLED,
        voice=HubVoice(enabled=settings.VOICE_ENABLED, model=settings.VOICE_MODEL),
        verifier=settings.VERIFIER_ENABLED,
        editing=_editing(request),
    )
