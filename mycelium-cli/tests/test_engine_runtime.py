# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""Unit tests for the host mediation drive loop (mycelium.engine.runtime).

Node-free: a fake :class:`EngineChannel` stands in for SLIM. When the engine
publishes a ``@handle`` prompt, the fake enqueues that agent's reply; the drive
loop reads it, interprets via a fake brain, steps NEGMAS, and emits the verdict.
Proves the *logic* end-to-end (discover → address → interpret → terminate →
emit ``commit:converged``). The real SLIM transport is validated live, separately.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

pytest.importorskip("negmas", reason="negmas not installed; install mycelium[engine]")

from mycelium.engine.runtime import EngineDrive
from mycelium.slim import l9


def _fake_brain(prompt: str, *, system: str = "", temperature: float = 0.3) -> str:
    if "identify the negotiable ISSUES" in prompt:
        return json.dumps({"issues": [{"name": "cap", "options": ["25", "30", "35"]}]})
    if "Interpret @" in prompt:
        if '"action":"counter"' in prompt:
            return json.dumps({"action": "counter", "offer": {"cap": "30"}})
        return json.dumps({"action": "accept"})
    return "Everyone's close on the cap; lock 30."


class _FakeChannel:
    """Records published content; auto-replies to each ``@handle`` prompt as that agent."""

    def __init__(self) -> None:
        self.published: list[dict[str, Any]] = []
        self._inbox: list[dict[str, Any]] = []

    async def publish(self, content: dict[str, Any]) -> None:
        self.published.append(content)
        data = l9.payload_data_of(content) or {}
        if data.get("action") == "position":  # a mediator prompt → enqueue the agent's reply
            for handle in l9.recipients_of(content):
                self._inbox.append(
                    l9.build_reply_content(
                        sender=handle,
                        recipients=["mediator-1"],
                        episode="ep",
                        parents=[],
                        text="I accept 30.",
                        payload_type="reply",
                        payload_data={"action": "reply"},
                    )
                )

    async def receive(self, *, timeout_s: float) -> dict[str, Any] | None:
        return self._inbox.pop(0) if self._inbox else None


@pytest.mark.asyncio
async def test_drive_converges_and_emits_commit() -> None:
    channel = _FakeChannel()
    drive = EngineDrive(
        engine_handle="mediator-1",
        room="portfolio",
        episode="ep",
        topic="topic",
        channel=channel,
        brain=_fake_brain,
        max_steps=12,
        round_timeout_s=2.0,
    )

    assignments = await drive.run(["growth", "risk"], {"growth": "I want 35", "risk": "I want 25"})

    assert assignments == {"cap": "30"}
    # A commit:converged verdict was published onto the channel (backend tail seam).
    commits = [
        c
        for c in channel.published
        if (l9.envelope_of(c) or {}).get("header", {}).get("kind") == "commit"
    ]
    assert len(commits) == 1
    assert commits[0]["l9"]["header"]["subkind"] == "converged"
    assert l9.payload_data_of(commits[0])["assignments"] == {"cap": "30"}
    # It addressed the agents (published prompts) but stopped below the cap.
    prompts = [
        c for c in channel.published if (l9.payload_data_of(c) or {}).get("action") == "position"
    ]
    assert 0 < len(prompts) < 12


@pytest.mark.asyncio
async def test_drive_rejects_when_no_issues() -> None:
    channel = _FakeChannel()
    drive = EngineDrive(
        engine_handle="mediator-1",
        room="portfolio",
        episode="ep",
        topic="topic",
        channel=channel,
        brain=lambda *a, **k: "not json",  # discovery yields nothing
        max_steps=6,
        round_timeout_s=1.0,
    )
    assignments = await drive.run(["growth", "risk"], {"growth": "?", "risk": "?"})
    assert assignments is None
    commits = [
        c
        for c in channel.published
        if (l9.envelope_of(c) or {}).get("header", {}).get("kind") == "commit"
    ]
    assert commits and commits[0]["l9"]["header"]["subkind"] == "rejected"
