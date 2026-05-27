# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""Opt-in shared context files via ``mycelium session join --context-files``.

Verifies:
- Context files are persisted on the participant row.
- Each file fans in to KXP with ``source=context_file``.
- An audit_events row records consent (path + sha256, no content).
- The ``shared_context_files`` array is exposed by the session loader used
  by tick fan-out.
"""

import asyncio
import hashlib

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.models import AuditEvent, Participant


def _sha256(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


@pytest.fixture
def captured_kxp(monkeypatch):
    captured: list[dict] = []

    async def _capture(*, room_name, sender_handle, content, source):
        captured.append(
            {
                "room_name": room_name,
                "sender_handle": sender_handle,
                "content": content,
                "source": source,
            }
        )

    monkeypatch.setattr("app.services.knowledge_fanin.fan_in", _capture)
    return captured


async def _drain():
    await asyncio.sleep(0)
    await asyncio.sleep(0)


@pytest.mark.asyncio
async def test_context_files_persisted_on_participant(client: AsyncClient, db_session):
    await client.post("/api/rooms", json={"name": "ctx-room"})

    body = "the entire SOUL.md content the user opted into sharing"
    resp = await client.post(
        "/api/rooms/ctx-room/sessions",
        json={
            "agent_handle": "alpha",
            "intent": "negotiating",
            "context_files": [
                {
                    "path": "/home/julia/.openclaw/agents/alpha/SOUL.md",
                    "content": body,
                    "sha256": _sha256(body),
                }
            ],
        },
    )
    assert resp.status_code == 201

    # Round-trip the participant row.
    rows = (await db_session.execute(select(Participant))).scalars().all()
    assert len(rows) == 1
    files = rows[0].context_files or []
    assert len(files) == 1
    assert files[0]["path"].endswith("SOUL.md")
    assert files[0]["sha256"] == _sha256(body)
    assert files[0]["content"] == body


@pytest.mark.asyncio
async def test_context_files_fan_in_to_kxp(client: AsyncClient, captured_kxp):
    await client.post("/api/rooms", json={"name": "ctx-kxp"})

    body = "deliberate context the user shared, well over thirty-two characters"
    await client.post(
        "/api/rooms/ctx-kxp/sessions",
        json={
            "agent_handle": "beta",
            "context_files": [{"path": "shared.md", "content": body, "sha256": _sha256(body)}],
        },
    )
    await _drain()

    sources = [c["source"] for c in captured_kxp]
    assert sources == ["context_file"]
    assert captured_kxp[0]["sender_handle"] == "beta"
    assert captured_kxp[0]["content"] == body


@pytest.mark.asyncio
async def test_context_files_audit_event_records_consent(client: AsyncClient, db_session):
    await client.post("/api/rooms", json={"name": "ctx-audit"})

    body = "audit me — content is captured on the participant, not in the audit row"
    await client.post(
        "/api/rooms/ctx-audit/sessions",
        json={
            "agent_handle": "gamma",
            "context_files": [
                {"path": "private.md", "content": body, "sha256": _sha256(body)},
            ],
        },
    )

    audits = (
        (
            await db_session.execute(
                select(AuditEvent).where(AuditEvent.audit_resource_identifier == "gamma")
            )
        )
        .scalars()
        .all()
    )
    assert len(audits) == 1
    info = audits[0].audit_information or {}
    assert info.get("kind") == "context_files_shared"
    assert info.get("room") == "ctx-audit"
    files = info.get("files") or []
    assert files == [{"path": "private.md", "sha256": _sha256(body)}]
    # Crucially: the audit row stores hashes, not contents.
    assert "content" not in files[0]


@pytest.mark.asyncio
async def test_load_shared_context_files_for_session(client: AsyncClient, db_session):
    """The tick fan-out loader returns files keyed by session display name."""
    from app.services.coordination import _load_shared_context_files

    await client.post("/api/rooms", json={"name": "ctx-load"})

    body = "shared content"
    join = await client.post(
        "/api/rooms/ctx-load/sessions",
        json={
            "agent_handle": "delta",
            "context_files": [{"path": "f.md", "content": body, "sha256": _sha256(body)}],
        },
    )
    sid = join.json()["coordination_session_id"]
    coord = await client.get(f"/api/coordination-sessions/{sid}")
    display_name = coord.json()["display_name"]

    files = await _load_shared_context_files(display_name, db=db_session)
    assert len(files) == 1
    assert files[0]["shared_by"] == "delta"
    assert files[0]["path"] == "f.md"
    assert files[0]["content"] == body
    assert files[0]["sha256"] == _sha256(body)


@pytest.mark.asyncio
async def test_no_context_files_no_audit_no_fan_in(client: AsyncClient, db_session, captured_kxp):
    """Joining without --context-files leaves audit + KXP untouched by this path."""
    await client.post("/api/rooms", json={"name": "ctx-empty"})
    await client.post(
        "/api/rooms/ctx-empty/sessions",
        json={"agent_handle": "epsilon", "intent": "no files"},
    )
    await _drain()

    audits = (
        (
            await db_session.execute(
                select(AuditEvent).where(AuditEvent.audit_resource_identifier == "epsilon")
            )
        )
        .scalars()
        .all()
    )
    assert audits == []
    assert captured_kxp == []
