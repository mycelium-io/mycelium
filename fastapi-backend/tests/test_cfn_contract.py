# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""Empirical Go-CFN contract fixes ported from the live-integration branch:
the memory-provider registration payload shape, the MAS-config passthrough
(retry/validation tuning), and the consensus `reason` field.
"""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.config import settings

# ── memory-provider registration payload (name / bool shapes) ─────────────────


def test_register_memory_provider_payload_shape(monkeypatch):
    """The Go mgmt plane wants `name` (not memory_provider_name) and a real
    bool for config.shared (not the string "True")."""
    from app import main

    monkeypatch.setattr(settings, "CFN_MGMT_URL", "http://mgmt:9000")
    captured = {}

    def _fake_post(url, json=None, timeout=None, **kw):
        captured["url"] = url
        captured["json"] = json
        resp = MagicMock()
        resp.status_code = 201
        resp.raise_for_status = MagicMock()
        return resp

    with patch("requests.post", side_effect=_fake_post):
        main._register_memory_provider()

    body = captured["json"]
    assert body["name"] == "mycelium"
    assert "memory_provider_name" not in body
    assert body["config"]["shared"] is True


# ── MAS-config passthrough (retry/validation tuning) ──────────────────────────


@pytest.mark.asyncio
async def test_ensure_mas_sends_mas_config(monkeypatch):
    """_ensure_mas sends mycelium's retry/validation policy under `config` (the
    live MultiAgenticSystemRequest field; an earlier `mas_config` key was
    silently dropped) so a room's MAS doesn't inherit the CFN default
    retry_max_attempts=3."""
    from app.models import Room
    from app.routes import rooms

    monkeypatch.setattr(settings, "CFN_MGMT_URL", "http://mgmt:9000")
    monkeypatch.setattr(settings, "WORKSPACE_ID", "ws-1")
    monkeypatch.setattr(settings, "CFN_RETRY_MAX_ATTEMPTS", 1)
    monkeypatch.setattr(settings, "CFN_VALIDATION_SCORE_INTERVENTION", 0.6)

    captured = {}

    class _FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, url, json=None):
            captured["json"] = json
            resp = MagicMock()
            resp.status_code = 201
            resp.raise_for_status = MagicMock()
            resp.json = MagicMock(return_value={"id": "mas-123"})
            return resp

    monkeypatch.setattr(rooms.httpx, "AsyncClient", lambda **kw: _FakeClient())

    db = AsyncMock()
    room = Room(name="platform-eng")
    mas_id = await rooms._ensure_mas(room, db)

    assert mas_id == "mas-123"
    assert captured["json"]["name"] == "platform-eng"
    assert "mas_config" not in captured["json"]  # the dropped field, must not regress
    assert captured["json"]["config"] == {
        "retry_max_attempts": 1,
        "validation_score_intervention": 0.6,
    }


# ── consensus `reason` threading ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_finish_cfn_threads_reason(monkeypatch, tmp_path):
    """_finish_cfn stamps the terminal reason (agreed/abort/timeout) onto the
    consensus payload so the UI can distinguish a timeout from a real abort."""
    monkeypatch.setattr(settings, "MYCELIUM_DATA_DIR", str(tmp_path))
    from app.services import coordination

    posted = []

    async def _fake_post(room_name, message_type, content):
        posted.append((message_type, json.loads(content)))

    monkeypatch.setattr(coordination, "_post_message", _fake_post)
    monkeypatch.setattr(coordination, "async_session_maker", MagicMock())

    # No _cfn_state entry → _finish_cfn takes the stateless path and just posts.
    await coordination._finish_cfn(
        "room-x", plan="Negotiation ended: timeout", assignments={}, broken=True, reason="timeout"
    )

    consensus = [c for t, c in posted if t == "coordination_consensus"]
    assert consensus, "no consensus message posted"
    assert consensus[0]["reason"] == "timeout"
    assert consensus[0]["broken"] is True


@pytest.mark.asyncio
async def test_finish_cfn_default_reason_agreed(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "MYCELIUM_DATA_DIR", str(tmp_path))
    from app.services import coordination

    posted = []

    async def _fake_post(room_name, message_type, content):
        posted.append((message_type, json.loads(content)))

    monkeypatch.setattr(coordination, "_post_message", _fake_post)
    monkeypatch.setattr(coordination, "async_session_maker", MagicMock())
    monkeypatch.setattr(coordination, "compile_plan", AsyncMock(return_value="# Plan\n\n- [ ] x\n"))

    await coordination._finish_cfn(
        "room-y", plan="budget=high", assignments={"budget": "high"}, broken=False
    )

    consensus = [c for t, c in posted if t == "coordination_consensus"]
    assert consensus and consensus[0]["reason"] == "agreed"
