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
    state: dict = {"response": httpx.Response(200, json={"status": "ok", "version": "9.9.9"})}

    def fake_get(url: str, timeout: float) -> httpx.Response:
        state["url"] = url
        response = state["response"]
        if isinstance(response, Exception):
            raise response
        response.request = httpx.Request("GET", url)
        return response

    monkeypatch.setattr(version_cmd.httpx, "get", fake_get)
    monkeypatch.setenv("MYCELIUM_API_URL", "http://hub.test:8000")
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


def test_cli_only_never_asks_the_hub(hub: dict) -> None:
    hub["response"] = AssertionError("hub was asked")
    result = runner.invoke(app, ["version", "--cli"])
    assert result.exit_code == 0, result.output
    assert result.output.strip() == __version__
