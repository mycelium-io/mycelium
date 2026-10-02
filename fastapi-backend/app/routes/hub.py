# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""Hub API: what this hub is set up with, for the people who use it.

GET /hub/settings   the model its agents use, its experiences, and whether it
                    shares usage stats

A hub is often a server nobody using it can reach the configuration of. This
lets a joined machine say what is set without being able to change it: it is
read-only, and it never says a key or an endpoint, only whether one is set.
Settings live where they always have (``config.toml`` on the hub's machine).
"""

from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel, Field

from app.config import settings
from app.services import patterns

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
    scenarios: int = Field(description="How many scenarios it has")


class HubSettings(BaseModel):
    """What this hub is set up with. Read-only: change it on the hub's machine."""

    model: HubModel
    experiences: list[HubExperience]
    personas_only: bool = Field(description="Patterns may start personas only, never workers")
    share_usage: bool = Field(description="Whether this hub sends its anonymous usage stats")


#: The experiences a hub can have, and what makes each one available. The Mac
#: app's catalogue (``mycelium/desktop/experiences.py``) names the same ones.
PATTERNS_EXPLORER = {
    "id": "patterns-explorer",
    "title": "Patterns Explorer",
    "description": "Watch a team of agents work through a business scenario, start to finish.",
    "open": "/patterns",
}


@router.get("/settings", response_model=HubSettings)
async def hub_settings() -> HubSettings:
    """What this hub is set up with, without a key or an address in it."""
    model = (settings.LLM_MODEL or "").strip() or None
    experiences: list[HubExperience] = []
    scenarios = len(patterns.pack_names())
    if scenarios:
        experiences.append(HubExperience(**PATTERNS_EXPLORER, scenarios=scenarios))
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
    )
