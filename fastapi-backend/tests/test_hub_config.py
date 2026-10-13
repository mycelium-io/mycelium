# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""Changing the hub's settings from the app's Hub page (``services/hub_config.py``).

Who may change them (a desktop hub, or a person when sign-in is on), how a
change is checked and handed to the CLI's ``config set``, that a key is never
sent back, and restarting a desktop hub so a change applies.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from app.config import settings
from app.services import hub_config

_CONTRACT = Path(__file__).resolve().parent.parent.parent / "contracts" / "hub-settings.json"


@pytest.fixture(autouse=True)
def fresh(monkeypatch):
    hub_config.reset()
    monkeypatch.delenv("MYCELIUM_HUB_MODE", raising=False)
    monkeypatch.delenv("MYCELIUM_CONFIG_CLI", raising=False)
    yield
    hub_config.reset()


@pytest.fixture
def desktop(monkeypatch):
    """A desktop hub, whose supervisor named the CLI."""
    monkeypatch.setenv("MYCELIUM_HUB_MODE", "desktop")
    monkeypatch.setenv("MYCELIUM_CONFIG_CLI", json.dumps(["/app/mycelium"]))


@pytest.fixture
def cli_calls(monkeypatch) -> list[tuple[list[str], str]]:
    """What the hub asked the CLI to do, in place of running it."""
    calls: list[tuple[list[str], str]] = []
    monkeypatch.setattr(hub_config, "_run", lambda argv, stdin: calls.append((argv, stdin)))
    return calls


def test_the_editable_settings_match_the_contract():
    contract = json.loads(_CONTRACT.read_text())
    assert contract["editable"] == hub_config.EDITABLE
    assert contract["restart_marker"] == hub_config.RESTART_MARKER


@pytest.mark.asyncio
async def test_a_hub_without_its_cli_stays_read_only_and_says_why(client):
    body = (await client.get("/api/hub/settings")).json()
    assert body["editing"]["may_edit"] is False
    assert "Docker" in body["editing"]["reason"]
    assert body["editing"]["values"] == {}
    refused = await client.patch("/api/hub/settings", json={"changes": {"verifier.enabled": True}})
    assert refused.status_code == 403


@pytest.mark.asyncio
async def test_a_desktop_hub_may_be_changed_and_sends_values_but_never_a_key(
    client, desktop, monkeypatch
):
    monkeypatch.setattr(settings, "LLM_API_KEY", "sk-ant-secret-value")
    monkeypatch.setattr(settings, "LLM_BASE_URL", "http://10.0.0.5:8080/v1")
    resp = await client.get("/api/hub/settings")
    editing = resp.json()["editing"]
    assert editing["may_edit"] is True
    assert editing["can_restart"] is True
    assert editing["values"]["llm.base_url"] == "http://10.0.0.5:8080/v1"
    assert editing["values"]["llm.api_key"] is True
    assert "sk-ant" not in resp.text
    # The desktop app sets these itself, so the page sends people there.
    assert set(editing["app_owned"]) == {
        "voice.enabled",
        "voice.model",
        "telemetry.send_product_analytics",
    }


@pytest.mark.asyncio
async def test_a_change_goes_through_config_set_with_the_value_on_stdin(client, desktop, cli_calls):
    resp = await client.patch(
        "/api/hub/settings",
        json={
            "changes": {
                "verifier.enabled": True,
                "llm.api_key": "sk-new",
                "worker.max_turns_per_room": 30,
                "llm.base_url": "",
            }
        },
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["restart_needed"] is True
    assert cli_calls == [
        (["/app/mycelium", "config", "set", "verifier.enabled", "-"], "true"),
        (["/app/mycelium", "config", "set", "llm.api_key", "-"], "sk-new"),
        (["/app/mycelium", "config", "set", "worker.max_turns_per_room", "-"], "30"),
        # Empty text clears the setting.
        (["/app/mycelium", "config", "set", "llm.base_url", "-"], ""),
    ]
    # The key is on stdin, never in the arguments.
    assert all("sk-new" not in arg for argv, _ in cli_calls for arg in argv)
    after = await client.get("/api/hub/settings")
    editing = after.json()["editing"]
    assert editing["pending"] == sorted(
        ["verifier.enabled", "llm.api_key", "worker.max_turns_per_room", "llm.base_url"]
    )
    # The page shows what was saved, not what the hub still runs with, and a
    # key still only as set.
    assert editing["values"]["verifier.enabled"] is True
    assert editing["values"]["worker.max_turns_per_room"] == 30
    assert editing["values"]["llm.base_url"] == ""
    assert editing["values"]["llm.api_key"] is True
    assert "sk-new" not in after.text


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("changes", "says"),
    [
        ({"auth.enabled": False}, "Not a setting"),
        ({"verifier.enabled": "yes"}, "on or off"),
        ({"worker.max_turns_per_room": 2.5}, "whole number"),
        ({"worker.pi_timeout_s": 0}, "more than 0"),
        ({"voice.model": "huge"}, "set in the app"),
    ],
)
async def test_a_bad_change_saves_nothing(client, desktop, cli_calls, changes, says):
    resp = await client.patch(
        "/api/hub/settings", json={"changes": {"verifier.enabled": True, **changes}}
    )
    assert resp.status_code == 422
    assert says in resp.json()["detail"]
    assert cli_calls == []


@pytest.mark.asyncio
async def test_a_choice_outside_its_options_is_refused_off_desktop(
    client, monkeypatch, cli_calls, as_principal
):
    monkeypatch.setenv("MYCELIUM_CONFIG_CLI", json.dumps(["/usr/bin/mycelium"]))
    as_principal("julia", role="user")
    resp = await client.patch("/api/hub/settings", json={"changes": {"voice.model": "huge"}})
    assert resp.status_code == 422
    assert "fast, accurate" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_with_sign_in_a_person_may_change_it_and_an_agent_may_not(
    client, monkeypatch, cli_calls, as_principal
):
    monkeypatch.setenv("MYCELIUM_CONFIG_CLI", json.dumps(["/usr/bin/mycelium"]))
    as_principal("builder", role="agent")
    agent = await client.patch("/api/hub/settings", json={"changes": {"verifier.enabled": True}})
    assert agent.status_code == 403
    assert "person" in agent.json()["detail"]
    as_principal("julia", role="user")
    person = await client.patch("/api/hub/settings", json={"changes": {"verifier.enabled": True}})
    assert person.status_code == 200
    # Off desktop the app has no switches of its own, so voice is changed here.
    editing = (await client.get("/api/hub/settings")).json()["editing"]
    assert editing["app_owned"] == []
    assert editing["can_restart"] is False


@pytest.mark.asyncio
async def test_without_sign_in_a_server_hub_stays_read_only(client, monkeypatch):
    monkeypatch.setenv("MYCELIUM_CONFIG_CLI", json.dumps(["/usr/bin/mycelium"]))
    editing = (await client.get("/api/hub/settings")).json()["editing"]
    assert editing["may_edit"] is False
    assert "sign-in" in editing["reason"]


@pytest.mark.asyncio
async def test_a_desktop_hub_restarts_after_it_answers(client, desktop, monkeypatch):
    asked: list[bool] = []
    monkeypatch.setattr(hub_config, "request_restart", lambda: asked.append(True))
    resp = await client.post("/api/hub/restart")
    assert resp.status_code == 202
    assert asked == []  # not before the answer is on its way
    await asyncio.sleep(0.4)
    assert asked == [True]


@pytest.mark.asyncio
async def test_a_hub_that_cant_restart_itself_says_so(client, monkeypatch, as_principal):
    monkeypatch.setenv("MYCELIUM_CONFIG_CLI", json.dumps(["/usr/bin/mycelium"]))
    as_principal("julia", role="user")
    resp = await client.post("/api/hub/restart")
    assert resp.status_code == 409


def test_asking_to_restart_leaves_the_marker_and_shuts_down(tmp_path, monkeypatch):
    signals: list[int] = []
    monkeypatch.setattr(settings, "MYCELIUM_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(hub_config.os, "kill", lambda pid, sig: signals.append(sig))
    hub_config.request_restart()
    assert (tmp_path / hub_config.RESTART_MARKER).exists()
    assert signals == [hub_config.signal.SIGINT]


def test_a_cli_that_refuses_says_why(monkeypatch, desktop):
    class Done:
        returncode = 1
        stdout = ""
        stderr = "Error: bad value\n"

    monkeypatch.setattr(hub_config.subprocess, "run", lambda *a, **k: Done())
    with pytest.raises(hub_config.HubConfigError, match="bad value"):
        hub_config.write({"llm.model": "x/y"}, [])
