# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""What the team learned, from the CLI: ``memory set --kind``, ``memory graph``,
``memory settle``.

The hub is a stand-in at httpx's transport, answering with the shapes it really
sends (the typed client parses them against ``openapi.json``).
"""

from __future__ import annotations

import json
import uuid
from pathlib import Path

import httpx
import pytest
from typer.testing import CliRunner

from mycelium.cli import app
from mycelium.knowledge_view import lines
from tests.conftest import StandInHub, install_stand_in_hub

runner = CliRunner()

TASK = "work/apple-pay-for-everyone"
GRAPH = {
    "tasks": [
        {"key": TASK, "title": "Apple Pay for everyone"},
        {"key": "work/payment-alerts", "title": "Payment alerts"},
    ],
    "memories": [
        {
            "key": "payments/stripe-dedupes",
            "kind": "fact",
            "title": "Stripe dedupes a retry with the same key",
            "by": "builder",
            "task": TASK,
            "open": False,
            "derived_from": [],
            "relates_to": [],
            "tags": [],
            "updated_at": "",
            "in_task": True,
        },
        {
            "key": "payments/new-key",
            "kind": "dead-end",
            "title": "A new key for every retry",
            "by": "builder:retry",
            "task": TASK,
            "open": False,
            "derived_from": ["payments/stripe-dedupes"],
            "relates_to": [],
            "tags": [],
            "updated_at": "",
            "in_task": True,
        },
        {
            "key": "payments/retries-reuse-key",
            "kind": "finding",
            "title": "Retries reuse the key",
            "by": "builder:retry",
            "task": TASK,
            "open": True,
            "derived_from": ["payments/stripe-dedupes"],
            "relates_to": [],
            "tags": ["flaky"],
            "updated_at": "",
            "in_task": True,
        },
        {
            "key": "payments/alert-on-captures",
            "kind": "finding",
            "title": "Alert on two captures in 10s",
            "by": "builder",
            "task": "work/payment-alerts",
            "open": False,
            "derived_from": ["payments/retries-reuse-key"],
            "relates_to": [],
            "tags": [],
            "updated_at": "",
            "in_task": False,
        },
    ],
}


@pytest.fixture(autouse=True)
def _isolate(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("MYCELIUM_ROOM_ID", "checkout")
    for name in ("MYCELIUM_API_URL", "MYCELIUM_AGENT_HANDLE", "HERDR_PANE_ID"):
        monkeypatch.delenv(name, raising=False)


@pytest.fixture
def hub(monkeypatch: pytest.MonkeyPatch) -> StandInHub:
    return install_stand_in_hub(monkeypatch)


def _saved(request: httpx.Request) -> tuple[int, list]:
    item = json.loads(request.content)["items"][0]
    return 201, [
        {
            "id": str(uuid.uuid4()),
            "room_name": "checkout",
            "key": item["key"],
            "value": item["value"],
            "created_by": item["created_by"],
            "version": 1,
            "created_at": "2026-11-16T10:00:00+00:00",
            "updated_at": "2026-11-16T10:00:00+00:00",
        }
    ]


def test_set_carries_what_was_learned_and_says_where_it_landed(hub: StandInHub):
    hub.answer = lambda r: _saved(r) if r.method == "POST" else GRAPH
    result = runner.invoke(
        app,
        [
            "memory",
            "set",
            "payments/retries-reuse-key",
            "Retries reuse the key",
            "--kind",
            "finding",
            "--derived-from",
            "payments/stripe-dedupes",
            "--task",
            TASK,
            "--open",
            "--as",
            "builder",
        ],
    )
    assert result.exit_code == 0, result.output
    (sent,) = hub.sent("POST", "/api/rooms/checkout/memory")
    meta = json.loads(sent.content)["items"][0]["meta"]
    assert meta == {
        "kind": "finding",
        "task": TASK,
        "derived-from": ["payments/stripe-dedupes"],
        "open": True,
    }
    out = " ".join(result.output.split())
    assert "A finding in Apple Pay for everyone. It's open." in out
    assert "It came from Stripe dedupes a retry with the same key (builder)" in out


def test_a_bad_kind_is_the_hubs_refusal(hub: StandInHub):
    said = "A memory's kind is one of fact, finding, dead-end, not 'hunch'."
    hub.answer = lambda _r: (
        422,
        {"detail": {"error": "memory.learned_kind", "message": said, "key": "payments/x"}},
    )
    result = runner.invoke(
        app, ["memory", "set", "payments/x", "Something", "--kind", "hunch", "--as", "builder"]
    )
    assert result.exit_code == 1
    assert said in " ".join(result.output.split())


def test_graph_reads_a_task_as_a_tree_of_what_came_from_what(hub: StandInHub):
    hub.answer = lambda _r: GRAPH
    result = runner.invoke(app, ["memory", "graph", "--task", TASK])
    assert result.exit_code == 0, result.output
    (sent,) = hub.sent("GET", "/api/rooms/checkout/knowledge")
    assert sent.url.params["task"] == TASK
    out = result.output.splitlines()
    assert out[0].split() == ["Apple", "Pay", "for", "everyone", "3", "memories", "1", "open"]
    fact = next(i for i, ln in enumerate(out) if "Stripe dedupes" in ln)
    dead = next(i for i, ln in enumerate(out) if "A new key for every retry" in ln)
    # What came from the fact sits under it, indented.
    assert dead > fact
    assert out[dead].startswith("  dead end")
    assert "in Payment alerts" in next(ln for ln in out if "Alert on two captures" in ln)


def test_a_long_title_is_cut_to_a_line():
    long = "A finding written as one long paragraph " * 6
    graph = {"tasks": [], "memories": [{**GRAPH["memories"][0], "title": long}]}
    (line,) = [ln for ln in lines(graph) if "A finding written" in ln]
    assert "…" in line
    assert len(long) > 200 and line.count("A finding written") < 6


def test_an_empty_graph_says_how_to_start_one():
    out = lines({"tasks": [], "memories": []}, TASK)
    assert "Nothing learned here yet" in " ".join(out)


def test_settle(hub: StandInHub):
    settled = {**GRAPH["memories"][2], "open": False}
    hub.answer = lambda _r: settled
    result = runner.invoke(
        app, ["memory", "settle", "payments/retries-reuse-key", "--as", "builder"]
    )
    assert result.exit_code == 0, result.output
    (sent,) = hub.sent("POST", "/api/rooms/checkout/knowledge/settle")
    assert json.loads(sent.content) == {"key": "payments/retries-reuse-key", "handle": "builder"}
    assert "Settled payments/retries-reuse-key" in result.output
