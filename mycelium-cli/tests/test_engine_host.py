# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""Unit tests for host-side engine dispatch (Stage B, approach A).

Node-free / LLM-free: the drive-active connector channel, roster sourcing, and
opening fetch are exercised with fakes. The end-to-end drive test simulates the
connector's receive-loop routing (inbound agent replies → the drive's queue) so
the real ``_QueueEngineChannel`` + ``drive_over_channel`` converge over a fake
publish, proving the seam without a SLIM node.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

import pytest

from mycelium.daemon.state import DaemonState
from mycelium.integrations.engine import host
from mycelium.protocol import AgentManifest
from mycelium.slim import l9


def _fake_brain(prompt: str, *, system: str = "", temperature: float = 0.3) -> str:
    if "identify the negotiable ISSUES" in prompt:
        return json.dumps({"issues": [{"name": "cap", "options": ["25", "30", "35"]}]})
    if "Interpret @" in prompt:
        if '"action":"counter"' in prompt:
            return json.dumps({"action": "counter", "offer": {"cap": "30"}})
        return json.dumps({"action": "accept"})
    return "Everyone's close on the cap; lock 30."


def _manifest(handle: str, adapter: str = "claude_code", kind: str | None = None) -> AgentManifest:
    if adapter == "engine":
        return AgentManifest(handle=handle, adapter="engine", kind=kind or "aligner")
    return AgentManifest(handle=handle, adapter="claude_code", cwd="/tmp/x")


# ── roster (local mirror) ────────────────────────────────────────────────────


def test_list_participants_excludes_engines_and_self(monkeypatch: pytest.MonkeyPatch) -> None:
    roster = {
        "mediator-1": _manifest("mediator-1", "engine"),
        "other-engine": _manifest("other-engine", "engine", "aligner"),
        "growth": _manifest("growth"),
        "risk": _manifest("risk"),
    }
    monkeypatch.setattr(host, "list_agent_handles", lambda _room: list(roster))
    monkeypatch.setattr(host, "load_manifest", lambda _room, h: roster.get(h))

    assert host.list_participants("r", "mediator-1") == ["growth", "risk"]


# ── openings (backend /messages API) ─────────────────────────────────────────


def _fake_httpx(data: dict[str, Any]) -> type:
    class _Resp:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, Any]:
            return data

    class _Client:
        async def __aenter__(self) -> _Client:
            return self

        async def __aexit__(self, *_a: object) -> bool:
            return False

        async def get(self, _url: str, params: dict | None = None) -> _Resp:
            return _Resp()

    return _Client


@pytest.mark.asyncio
async def test_fetch_openings_latest_per_participant_and_stub(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Newest-first, as the backend returns them.
    data = {
        "messages": [
            {"sender_handle": "growth", "content": "latest growth position"},
            {"sender_handle": "risk", "content": "risk opening"},
            {"sender_handle": "growth", "content": "older growth position"},
        ]
    }
    monkeypatch.setattr(host.httpx, "AsyncClient", lambda **_k: _fake_httpx(data)())

    openings = await host.fetch_openings("http://x", "r", ["growth", "risk", "exec"])

    assert openings["growth"] == "latest growth position"  # newest wins
    assert openings["risk"] == "risk opening"
    assert "no opening position" in openings["exec"]  # silent agent → stub


@pytest.mark.asyncio
async def test_fetch_openings_all_stubs_on_fetch_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    def _boom(**_k: object) -> None:
        raise RuntimeError("backend down")

    monkeypatch.setattr(host.httpx, "AsyncClient", _boom)
    openings = await host.fetch_openings("http://x", "r", ["growth"])
    assert "no opening position" in openings["growth"]


# ── _QueueEngineChannel ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_queue_channel_receive_timeout_returns_none() -> None:
    published: list[dict] = []

    async def _publish(c: dict) -> None:
        published.append(c)

    channel = host._QueueEngineChannel(_publish, asyncio.Queue())
    assert await channel.receive(timeout_s=0.01) is None
    await channel.publish({"hello": "world"})
    assert published == [{"hello": "world"}]


# ── dispatch_engine (end-to-end over the connector-backed channel) ───────────


def _agent_reply(handle: str) -> dict:
    return l9.build_reply_content(
        sender=handle,
        recipients=["mediator-1"],
        episode="ep",
        parents=[],
        text="I accept 30.",
        payload_type="reply",
        payload_data={"action": "reply"},
    )


@pytest.mark.asyncio
async def test_dispatch_engine_drives_to_convergence(monkeypatch: pytest.MonkeyPatch) -> None:
    from mycelium.config import MyceliumConfig

    monkeypatch.setattr(host, "list_participants", lambda _room, _h: ["growth", "risk"])

    async def _openings(*_a: object, **_k: object) -> dict[str, str]:
        return {"growth": "I want 35", "risk": "I want 25"}

    monkeypatch.setattr(host, "fetch_openings", _openings)
    monkeypatch.setattr(host, "build_host_brain", lambda _cfg, _ep: _fake_brain)

    state = DaemonState()
    published: list[dict] = []

    async def publish(content: dict) -> None:
        published.append(content)
        # Simulate the connector's receive-loop routing: an agent reply to each
        # mediator prompt lands in the drive's queue.
        if (l9.payload_data_of(content) or {}).get("action") == "position":
            for handle in l9.recipients_of(content):
                queue = state.active_drives.get("mediator-1")
                if queue is not None:
                    queue.put_nowait(_agent_reply(handle))

    await host.dispatch_engine(
        config=MyceliumConfig(),
        state=state,
        room="portfolio",
        handle="mediator-1",
        kind="aligner",
        publish=publish,
    )

    # The queue was deregistered after the drive (also the re-summon guard clears).
    assert "mediator-1" not in state.active_drives
    # A commit:converged verdict was published on the channel.
    commits = [
        c for c in published if (l9.envelope_of(c) or {}).get("header", {}).get("kind") == "commit"
    ]
    assert len(commits) == 1
    assert commits[0]["l9"]["header"]["subkind"] == "converged"
    assert l9.payload_data_of(commits[0])["assignments"] == {"cap": "30"}


@pytest.mark.asyncio
async def test_dispatch_engine_ignores_resummon_while_active(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from mycelium.config import MyceliumConfig

    called = False

    def _should_not_run(_room: str, _h: str) -> list[str]:
        nonlocal called
        called = True
        return []

    monkeypatch.setattr(host, "list_participants", _should_not_run)

    state = DaemonState()
    state.active_drives["mediator-1"] = asyncio.Queue()  # a drive is already in flight

    async def publish(_c: dict) -> None:
        return None

    await host.dispatch_engine(
        config=MyceliumConfig(),
        state=state,
        room="r",
        handle="mediator-1",
        kind="aligner",
        publish=publish,
    )
    assert called is False  # short-circuited before sourcing anything
    assert "mediator-1" in state.active_drives  # the in-flight drive's queue untouched


@pytest.mark.asyncio
async def test_dispatch_engine_no_participants_noop(monkeypatch: pytest.MonkeyPatch) -> None:
    from mycelium.config import MyceliumConfig

    monkeypatch.setattr(host, "list_participants", lambda _room, _h: [])
    published: list[dict] = []

    async def publish(c: dict) -> None:
        published.append(c)

    state = DaemonState()
    await host.dispatch_engine(
        config=MyceliumConfig(),
        state=state,
        room="r",
        handle="mediator-1",
        kind="aligner",
        publish=publish,
    )
    assert published == []  # nothing to negotiate → no prompts, no verdict
    assert "mediator-1" not in state.active_drives  # queue released
