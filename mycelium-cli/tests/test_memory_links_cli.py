# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""``mycelium memory links`` — the CLI view of a room's link graph.

Node-free: the hub is a stand-in at httpx's transport, so these exercise CLI
plumbing — room resolution, which link endpoint each flag hits, and how resolved
vs broken edges are phrased for a reader.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import httpx
import pytest
from typer.testing import CliRunner

from mycelium.cli import app
from tests.conftest import StandInHub, install_stand_in_hub

runner = CliRunner()


@pytest.fixture(autouse=True)
def _isolate(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("MYCELIUM_ROOM_ID", "demo")


@pytest.fixture
def hub(monkeypatch: pytest.MonkeyPatch) -> StandInHub:
    return install_stand_in_hub(monkeypatch)


def _answer(hub: StandInHub, payload: dict[str, Any]) -> None:
    hub.answer = lambda _request: payload


def _urls(hub: StandInHub) -> list[str]:
    return [str(r.url) for r in hub.requests if isinstance(r, httpx.Request)]


def _link(target: str, **over: object) -> dict:
    return {
        "target": target,
        "kind": "wikilink",
        "anchor": None,
        "label": None,
        "relation": None,
        "raw": f"[[{target}]]",
        "source": None,
        "resolved": True,
        "error": None,
        **over,
    }


def _integrity(**over: object) -> dict:
    return {
        "broken": [],
        "orphans": [],
        "roots": [],
        "leaves": [],
        "total_memories": 0,
        "total_links": 0,
        **over,
    }


def _expansion(target: str, **over: object) -> dict:
    return {
        "target": target,
        "anchor": None,
        "raw": f"![[{target}]]",
        "expanded": True,
        "error": None,
        **over,
    }


def test_links_shows_both_directions(hub: StandInHub) -> None:
    _answer(
        hub,
        {
            "key": "decisions/db",
            "outbound": [_link("context/stack")],
            "backlinks": [_link("decisions/db", source="procedures/deploy")],
        },
    )

    result = runner.invoke(app, ["memory", "links", "decisions/db", "--room", "demo"])

    assert result.exit_code == 0
    assert "context/stack" in result.output
    assert "procedures/deploy" in result.output


def test_links_explains_a_broken_edge(hub: StandInHub) -> None:
    _answer(
        hub,
        {
            "key": "decisions/db",
            "outbound": [_link("gone", resolved=False, error="not_found")],
            "backlinks": [],
        },
    )

    result = runner.invoke(app, ["memory", "links", "decisions/db", "--room", "demo"])

    assert result.exit_code == 0
    assert "no such memory" in result.output


def test_links_names_the_relation_for_a_typed_edge(hub: StandInHub) -> None:
    _answer(
        hub,
        {
            "key": "decisions/db",
            "outbound": [_link("decisions/db-v1", kind="relation", relation="supersedes")],
            "backlinks": [],
        },
    )

    result = runner.invoke(app, ["memory", "links", "decisions/db", "--room", "demo"])

    assert "supersedes" in result.output


def test_links_reports_an_unlinked_memory_plainly(hub: StandInHub) -> None:
    _answer(hub, {"key": "a", "outbound": [], "backlinks": []})

    result = runner.invoke(app, ["memory", "links", "a", "--room", "demo"])

    assert result.exit_code == 0
    assert "links to nothing" in result.output


def test_links_requires_a_key_or_check(hub: StandInHub) -> None:
    result = runner.invoke(app, ["memory", "links", "--room", "demo"])

    assert result.exit_code == 1
    assert "--check" in result.output


def test_check_hits_the_integrity_endpoint(hub: StandInHub) -> None:
    _answer(
        hub,
        _integrity(
            broken=[_link("gone", source="decisions/db", resolved=False, error="not_found")],
            orphans=["log/episodes/abc"],
            total_memories=4,
            total_links=2,
        ),
    )

    result = runner.invoke(app, ["memory", "links", "--check", "--room", "demo"])

    assert result.exit_code == 0
    assert any("/links/integrity" in url for url in _urls(hub))
    assert "Broken links (1)" in result.output
    assert "log/episodes/abc" in result.output


def test_check_reports_a_clean_room(hub: StandInHub) -> None:
    _answer(hub, _integrity(total_memories=2, total_links=1))

    result = runner.invoke(app, ["memory", "links", "--check", "--room", "demo"])

    assert "No broken links" in result.output


def test_get_expand_renders_transclusions(hub: StandInHub) -> None:
    _answer(
        hub,
        {
            "key": "reader",
            "rendered": "Recall: A definition.",
            "expansions": [_expansion("glossary/term")],
            "found": True,
        },
    )

    result = runner.invoke(app, ["memory", "get", "reader", "--room", "demo", "--expand"])

    assert result.exit_code == 0
    assert any("/links/expand" in url for url in _urls(hub))
    assert "Recall: A definition." in result.output


def test_get_expand_calls_out_a_refused_embed(hub: StandInHub) -> None:
    _answer(
        hub,
        {
            "key": "reader",
            "rendered": "See ![[context/plain]]",
            "expansions": [
                _expansion("context/plain", expanded=False, error="not_expandable"),
            ],
            "found": True,
        },
    )

    result = runner.invoke(app, ["memory", "get", "reader", "--room", "demo", "--expand"])

    assert "Not expanded" in result.output
    assert "target is not expandable" in result.output
