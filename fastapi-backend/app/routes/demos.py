# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""Web-triggered coordinations — a thin proxy to the host-side hub runner.

The runner (``mycelium hub serve``) lives on the host next to the OpenClaw
gateway and actually provisions the agents; the backend can't, because a
container can't restart a host process or edit ``~/.openclaw``. These endpoints
just forward to it so the web GUI can kick off a demo with no terminal.

Gated on ``settings.HUB_RUNNER_URL``: unset → 404 (feature off — the default on
every end-user local install). Only the internal hub points it at a runner.
"""

from __future__ import annotations

from typing import Any

import httpx
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.config import settings

router = APIRouter(tags=["demos"])


class DemoStartRequest(BaseModel):
    """Demo launch parameters. All optional — the runner fills sane defaults
    (default scenario, openclaw adapter, scenario-derived room name)."""

    scenario: str | None = None
    adapter: str | None = None
    model: str | None = None
    auth_from: str | None = None
    room: str | None = None


def _runner_base() -> str:
    base = settings.HUB_RUNNER_URL
    if not base:
        raise HTTPException(status_code=404, detail="host runner not configured")
    return base.rstrip("/")


def _runner_headers() -> dict[str, str]:
    token = settings.HUB_RUNNER_TOKEN
    return {"Authorization": f"Bearer {token}"} if token else {}


async def _forward(method: str, path: str, *, json_body: Any = None) -> Any:
    """Forward to the runner and pass its status + JSON body through unchanged."""
    base = _runner_base()
    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            resp = await client.request(
                method, f"{base}{path}", json=json_body, headers=_runner_headers()
            )
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail=f"host runner unreachable: {exc}") from exc

    try:
        payload = resp.json()
    except ValueError:
        payload = {"error": resp.text}
    if resp.status_code >= 400:
        raise HTTPException(status_code=resp.status_code, detail=payload)
    return payload


@router.get("/demos/scenarios")
async def list_demo_scenarios() -> Any:
    """Discoverable demo scenarios (proxied from the host runner)."""
    return await _forward("GET", "/scenarios")


@router.post("/demos")
async def start_demo(body: DemoStartRequest) -> Any:
    """Kick off a demo coordination on the host. Returns ``{job_id, room}``."""
    return await _forward("POST", "/demos", json_body=body.model_dump(exclude_none=True))


@router.get("/demos/{job_id}")
async def get_demo_job(job_id: str) -> Any:
    """Poll a demo provisioning job's status."""
    return await _forward("GET", f"/demos/{job_id}")
