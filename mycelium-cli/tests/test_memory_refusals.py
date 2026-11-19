# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""How the CLI says a refused memory write: the hub's sentence, then its code.

The hub refuses a write its kind doesn't allow with ``{"error": <code>,
"message": ...}`` (contracts/memory-kinds.json). ``memory set`` prints the
sentence a person reads and the code an agent can match on, never the raw
refusal, for every code the contract has.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from mycelium.cli import app
from mycelium.client import hub_error_detail
from tests.conftest import StandInHub, install_stand_in_hub

runner = CliRunner()

CONTRACT = json.loads(
    (Path(__file__).resolve().parents[2] / "contracts" / "memory-kinds.json").read_text()
)


@pytest.fixture(autouse=True)
def _isolate(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("MYCELIUM_ROOM_ID", "demo")
    for name in ("MYCELIUM_API_URL", "MYCELIUM_AGENT_HANDLE", "HERDR_PANE_ID"):
        monkeypatch.delenv(name, raising=False)


@pytest.fixture
def hub(monkeypatch: pytest.MonkeyPatch) -> StandInHub:
    return install_stand_in_hub(monkeypatch)


def _refusal(code: str, message: str) -> dict:
    return {"detail": {"error": code, "message": message, "key": "uploads/plan.md"}}


@pytest.mark.parametrize("code", sorted(CONTRACT["codes"]))
def test_every_refusal_reads_as_its_sentence_and_code(code: str):
    body = json.dumps(_refusal(code, "Why it was refused.")).encode()
    assert hub_error_detail(body) == f"Why it was refused. ({code})"


@pytest.mark.parametrize("code", sorted(CONTRACT["codes"]))
def test_memory_set_says_the_hub_s_reason(hub: StandInHub, code: str):
    said = "An upload is its file, and can't be edited. Upload the file again to replace it."
    hub.answer = lambda _r: (CONTRACT["codes"][code], _refusal(code, said))
    result = runner.invoke(app, ["memory", "set", "uploads/plan.md", "edited"])
    assert result.exit_code == 1
    out = " ".join(result.output.split())
    assert said in out
    assert f"({code})" in out
    assert "{'error'" not in out


def test_a_plain_refusal_still_reads_as_it_is():
    assert hub_error_detail(json.dumps({"detail": "Room not found"}).encode()) == "Room not found"
