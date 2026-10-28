# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

import json

import httpx
import pytest
from typer.testing import CliRunner

from mycelium import __version__
from mycelium.cli import app
from mycelium.commands import version as version_cmd

runner = CliRunner()


@pytest.fixture
def hub(monkeypatch: pytest.MonkeyPatch) -> dict:
    from mycelium import identity

    state: dict = {
        "response": httpx.Response(200, json={"status": "ok", "version": "9.9.9"}),
        # What /api/whoami answers; None is a hub with sign-in off answering nothing.
        "whoami": None,
    }

    def fake_get(url: str, timeout: float) -> httpx.Response:
        state["url"] = url
        response = state["response"]
        if isinstance(response, Exception):
            raise response
        if callable(response):
            response = response(url)
        response.request = httpx.Request("GET", url)
        return response

    monkeypatch.setattr(version_cmd.httpx, "get", fake_get)
    monkeypatch.setattr(identity, "_hub_whoami", lambda _config: state["whoami"])
    monkeypatch.setenv("MYCELIUM_API_URL", "http://hub.test:8000")
    for name in ("MYCELIUM_AGENT_PANE", "MYCELIUM_AGENT_HANDLE", "HERDR_PANE_ID"):
        monkeypatch.delenv(name, raising=False)
    return state


def test_prints_cli_and_hub(hub: dict) -> None:
    result = runner.invoke(app, ["version"])
    assert result.exit_code == 0, result.output
    assert f"cli  {__version__}" in result.output
    assert "hub  9.9.9  (http://hub.test:8000)" in result.output
    assert hub["url"] == "http://hub.test:8000/health"


def test_unreachable_hub_is_said_plainly(hub: dict) -> None:
    hub["response"] = httpx.ConnectError("refused")
    result = runner.invoke(app, ["version"])
    assert result.exit_code == 0, result.output
    assert "hub  unreachable" in result.output


def test_hub_error_status_reads_unreachable(hub: dict) -> None:
    hub["response"] = httpx.Response(503, text="down")
    result = runner.invoke(app, ["version"])
    assert "hub  unreachable" in result.output


def test_json(hub: dict) -> None:
    result = runner.invoke(app, ["--json", "version"])
    assert result.exit_code == 0, result.output
    assert json.loads(result.output) == {
        "cli": __version__,
        "hub": "9.9.9",
        "hub_url": "http://hub.test:8000",
    }


def test_json_after_the_command(hub: dict) -> None:  # noqa: ARG001 - the stubbed hub
    result = runner.invoke(app, ["version", "--json"])
    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["hub"] == "9.9.9"


def test_a_hub_reached_at_its_apps_address_is_asked_under_api(hub: dict) -> None:
    """The app answers only /api/*, so a bare /health there is a 404, not a dead hub."""

    def app_address(url: str) -> httpx.Response:
        if url.endswith("/api/health"):
            return httpx.Response(200, json={"status": "ok", "version": "9.9.9"})
        return httpx.Response(404)

    hub["response"] = app_address
    result = runner.invoke(app, ["version"])
    assert "hub  9.9.9" in result.output
    assert hub["url"] == "http://hub.test:8000/api/health"


def test_a_refused_credential_is_said_with_its_fix_not_as_unreachable(hub: dict) -> None:
    hub["whoami"] = {"gated": True, "handle": None}
    result = runner.invoke(app, ["version"])
    assert "hub  9.9.9" in result.output
    assert "no credential: this terminal sends none" in result.output
    assert "mycelium login" in result.output
    assert "unreachable" not in result.output


def test_an_agents_pane_is_pointed_at_its_runner_not_at_signing_in(
    hub: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    hub["whoami"] = {"gated": True, "handle": None}
    monkeypatch.setenv("MYCELIUM_AGENT_PANE", "1")
    monkeypatch.setenv("MYCELIUM_AGENT_HANDLE", "coder")
    result = runner.invoke(app, ["version"])
    out = " ".join(result.output.split())
    assert "This is @coder's pane" in out
    assert "mycelium runner status" in out
    assert "mycelium login" not in out


def test_an_accepted_credential_says_who_and_from_where(hub: dict) -> None:
    hub["whoami"] = {"gated": True, "handle": "avery"}
    result = runner.invoke(app, ["--json", "version"])
    body = json.loads(result.output)
    assert body["credential"]["accepted"] is True
    assert body["credential"]["as"] == "avery"


def test_cli_only_never_asks_the_hub(hub: dict) -> None:
    hub["response"] = AssertionError("hub was asked")
    result = runner.invoke(app, ["version", "--cli"])
    assert result.exit_code == 0, result.output
    assert result.output.strip() == __version__
