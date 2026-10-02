# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""/api/hub/settings: what a hub is set up with, read-only, with no secret in it.

A joined machine cannot reach the hub's config.toml, so the hub says what is set:
the model and whether a key is set (never the key, never the address it answers
at), the experiences it has, personas only, and usage sharing.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.config import settings
from app.routes.hub import EXPERIENCES

_CONTRACT = Path(__file__).resolve().parent.parent.parent / "contracts" / "experiences.json"


@pytest.mark.asyncio
async def test_a_hub_says_its_model_without_the_key_or_address(client, monkeypatch):
    monkeypatch.setattr(settings, "LLM_MODEL", "anthropic/claude-sonnet-4-6")
    monkeypatch.setattr(settings, "LLM_API_KEY", "sk-ant-secret-value")
    monkeypatch.setattr(settings, "LLM_BASE_URL", "http://10.0.0.5:8080/v1")
    monkeypatch.setattr(settings, "PATTERNS_DIR", "")
    resp = await client.get("/api/hub/settings")
    assert resp.status_code == 200
    body = resp.json()
    assert body["model"] == {
        "model": "anthropic/claude-sonnet-4-6",
        "provider": "anthropic",
        "has_key": True,
        "custom_endpoint": True,
    }
    assert "sk-ant" not in resp.text
    assert "10.0.0.5" not in resp.text
    assert body["experiences"] == []


@pytest.mark.asyncio
async def test_a_hub_with_a_pack_has_the_patterns_explorer(client, monkeypatch, tmp_path):
    for name in ("approval-gate-agent", "supervisor-worker"):
        folder = tmp_path / "scenarios" / name
        folder.mkdir(parents=True)
        (folder / "scenario.yaml").write_text("pattern: x\n")
    monkeypatch.setattr(settings, "PATTERNS_DIR", str(tmp_path))
    monkeypatch.setattr(settings, "PATTERNS_PERSONAS_ONLY", True)
    monkeypatch.setattr(settings, "TELEMETRY_SEND_PRODUCT_ANALYTICS", False)
    body = (await client.get("/api/hub/settings")).json()
    assert [(x["id"], x["open"], x["scenarios"]) for x in body["experiences"]] == [
        ("patterns-explorer", "/patterns", 2)
    ]
    assert body["personas_only"] is True
    assert body["share_usage"] is False


@pytest.mark.asyncio
async def test_settings_cannot_be_changed_here(client):
    assert (await client.put("/api/hub/settings", json={})).status_code == 405
    assert (await client.post("/api/hub/settings", json={})).status_code == 405


def test_the_experiences_are_the_contracts():
    contract = json.loads(_CONTRACT.read_text())
    assert contract["experiences"] == EXPERIENCES
