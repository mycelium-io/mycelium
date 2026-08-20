# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""``mycelium memory links`` — the CLI view of a room's link graph.

Node-free: ``httpx`` is stubbed, so these exercise CLI plumbing — room
resolution, which link endpoint each flag hits, and how resolved vs broken
edges are phrased for a reader.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from mycelium.cli import app
from tests.conftest import FakeHTTPX, FakeResp

runner = CliRunner()


@pytest.fixture(autouse=True)
def _isolate(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("MYCELIUM_ROOM_ID", "demo")


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


def test_links_shows_both_directions(fake_httpx: FakeHTTPX) -> None:
    fake_httpx.respond_with(
        lambda *_a: FakeResp(
            {
                "key": "decisions/db",
                "outbound": [_link("context/stack")],
                "backlinks": [_link("decisions/db", source="procedures/deploy")],
            }
        )
    )

    result = runner.invoke(app, ["memory", "links", "decisions/db", "--room", "demo"])

    assert result.exit_code == 0
    assert "context/stack" in result.output
    assert "procedures/deploy" in result.output


def test_links_explains_a_broken_edge(fake_httpx: FakeHTTPX) -> None:
    fake_httpx.respond_with(
        lambda *_a: FakeResp(
            {
                "key": "decisions/db",
                "outbound": [_link("gone", resolved=False, error="not_found")],
                "backlinks": [],
            }
        )
    )

    result = runner.invoke(app, ["memory", "links", "decisions/db", "--room", "demo"])

    assert result.exit_code == 0
    assert "no such memory" in result.output


def test_links_names_the_relation_for_a_typed_edge(fake_httpx: FakeHTTPX) -> None:
    fake_httpx.respond_with(
        lambda *_a: FakeResp(
            {
                "key": "decisions/db",
                "outbound": [_link("decisions/db-v1", kind="relation", relation="supersedes")],
                "backlinks": [],
            }
        )
    )

    result = runner.invoke(app, ["memory", "links", "decisions/db", "--room", "demo"])

    assert "supersedes" in result.output


def test_links_reports_an_unlinked_memory_plainly(fake_httpx: FakeHTTPX) -> None:
    fake_httpx.respond_with(lambda *_a: FakeResp({"key": "a", "outbound": [], "backlinks": []}))

    result = runner.invoke(app, ["memory", "links", "a", "--room", "demo"])

    assert result.exit_code == 0
    assert "links to nothing" in result.output


def test_links_requires_a_key_or_check(fake_httpx: FakeHTTPX) -> None:
    result = runner.invoke(app, ["memory", "links", "--room", "demo"])

    assert result.exit_code == 1
    assert "--check" in result.output


def test_check_hits_the_integrity_endpoint(fake_httpx: FakeHTTPX) -> None:
    fake_httpx.respond_with(
        lambda *_a: FakeResp(
            {
                "broken": [
                    {"source": "decisions/db", "target": "gone", "error": "not_found"},
                ],
                "orphans": ["log/episodes/abc"],
                "total_memories": 4,
                "total_links": 2,
            }
        )
    )

    result = runner.invoke(app, ["memory", "links", "--check", "--room", "demo"])

    assert result.exit_code == 0
    assert any("/links/integrity" in url for _m, url, _p in fake_httpx.calls)
    assert "Broken links (1)" in result.output
    assert "log/episodes/abc" in result.output


def test_check_reports_a_clean_room(fake_httpx: FakeHTTPX) -> None:
    fake_httpx.respond_with(
        lambda *_a: FakeResp({"broken": [], "orphans": [], "total_memories": 2, "total_links": 1})
    )

    result = runner.invoke(app, ["memory", "links", "--check", "--room", "demo"])

    assert "No broken links" in result.output


def test_get_expand_renders_transclusions(fake_httpx: FakeHTTPX) -> None:
    fake_httpx.respond_with(
        lambda *_a: FakeResp(
            {
                "key": "reader",
                "rendered": "Recall: A definition.",
                "expansions": [{"target": "glossary/term", "anchor": None, "expanded": True}],
                "found": True,
            }
        )
    )

    result = runner.invoke(app, ["memory", "get", "reader", "--room", "demo", "--expand"])

    assert result.exit_code == 0
    assert any("/links/expand" in url for _m, url, _p in fake_httpx.calls)
    assert "Recall: A definition." in result.output


def test_get_expand_calls_out_a_refused_embed(fake_httpx: FakeHTTPX) -> None:
    fake_httpx.respond_with(
        lambda *_a: FakeResp(
            {
                "key": "reader",
                "rendered": "See ![[context/plain]]",
                "expansions": [
                    {
                        "target": "context/plain",
                        "anchor": None,
                        "expanded": False,
                        "error": "not_expandable",
                    }
                ],
                "found": True,
            }
        )
    )

    result = runner.invoke(app, ["memory", "get", "reader", "--room", "demo", "--expand"])

    assert "Not expanded" in result.output
    assert "target is not expandable" in result.output
