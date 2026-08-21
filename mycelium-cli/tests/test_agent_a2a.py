# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""`mycelium agent create --adapter a2a` — register an external A2A endpoint.

The a2a family has no local runtime: the CLI posts to the backend's a2a-agents
route (which resolves the card), rather than building a manifest locally. These
tests mock the hub so they stay offline, and pin the integration-registry
invariants for the new family.
"""

from __future__ import annotations

from contextlib import contextmanager
from unittest.mock import MagicMock

import pytest
from typer.testing import CliRunner

from mycelium.commands import agent as agent_cmd
from mycelium.integrations import get_adapter
from mycelium.protocol import AGENT_ADAPTERS, AgentManifest

runner = CliRunner()


@pytest.fixture
def fake_hub(monkeypatch):
    """Route the create command's config + hub call through fakes."""
    monkeypatch.setattr(agent_cmd.MyceliumConfig, "load", staticmethod(lambda: MagicMock()))
    monkeypatch.setattr(agent_cmd, "_resolve_room", lambda _c, _r: "portfolio")
    monkeypatch.setattr(agent_cmd, "_default_owner", lambda owner, handle: owner or handle)

    posts: list[dict] = []

    def _install(response):
        @contextmanager
        def _client(_config, **_kwargs):
            fake = MagicMock()

            def _post(url, json):
                posts.append({"url": url, "json": json})
                return response

            fake.post = _post
            yield fake

        monkeypatch.setattr(agent_cmd, "hub_client", _client)

    return _install, posts


def test_create_a2a_posts_to_backend(fake_hub):
    install, posts = fake_hub
    resp = MagicMock(status_code=201)
    resp.json.return_value = {
        "handle": "researcher",
        "adapter": "a2a",
        "a2a_endpoint": "https://remote.example/rpc",
        "a2a_skills": ["deep_search"],
    }
    install(resp)

    result = runner.invoke(
        agent_cmd.app,
        ["create", "researcher", "--adapter", "a2a", "--card", "https://remote.example"],
    )
    assert result.exit_code == 0, result.output
    assert posts and posts[0]["url"] == "/api/rooms/portfolio/a2a-agents"
    assert posts[0]["json"]["card"] == "https://remote.example"
    assert "deep_search" in result.output


def test_create_a2a_requires_card(fake_hub):
    install, _posts = fake_hub
    install(MagicMock(status_code=201))
    result = runner.invoke(agent_cmd.app, ["create", "researcher", "--adapter", "a2a"])
    assert result.exit_code == 1
    assert "--card" in result.output


def test_create_a2a_surfaces_bad_card_detail(fake_hub):
    install, _posts = fake_hub
    resp = MagicMock(status_code=502)
    resp.json.return_value = {"detail": "Could not resolve A2A card: no card found"}
    install(resp)

    result = runner.invoke(
        agent_cmd.app,
        ["create", "researcher", "--adapter", "a2a", "--card", "https://nope"],
    )
    assert result.exit_code == 1
    assert "Could not resolve A2A card" in result.output


def test_a2a_is_a_registered_family():
    assert "a2a" in AGENT_ADAPTERS
    impl = get_adapter("a2a", card="https://remote.example")
    assert impl.name == "a2a"
    assert impl.lifecycle == "backend_engine"


def test_a2a_manifest_round_trips():
    manifest = get_adapter("a2a", card="https://remote.example").build_manifest(
        handle="researcher",
        opts=agent_cmd.AddOptions(room="portfolio"),
        description="does research",
        allow_from=[],
    )
    assert manifest.adapter == "a2a"
    assert manifest.a2a_card == "https://remote.example"
    # a manifest without a card is rejected — an a2a agent must name its endpoint
    with pytest.raises(ValueError, match="a2a_card"):
        AgentManifest(handle="x", adapter="a2a")
