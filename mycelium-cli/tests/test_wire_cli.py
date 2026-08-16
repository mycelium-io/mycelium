# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""``mycelium l9 send`` / ``mycelium slim send`` — hidden dev/testing plumbing.

Node-free: ``wire.publish_once`` (the SLIM join/publish primitive) is stubbed so
these exercise the CLI plumbing — hidden-from-help registration, kind/subkind
validation *before* anything is published, envelope construction, and the
``slim send`` text/json exclusivity check.
"""

from __future__ import annotations

import json

import pytest
from typer.testing import CliRunner

from mycelium.cli import app
from mycelium.commands import wire
from mycelium.config import MyceliumConfig
from mycelium.slim import l9
from mycelium.slim.member import SlimSendError

runner = CliRunner()


@pytest.fixture(autouse=True)
def _stub_config(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_config = MyceliumConfig()
    fake_config.rooms.active = "demo"
    monkeypatch.setattr(wire.MyceliumConfig, "load", classmethod(lambda _cls: fake_config))


def test_l9_and_slim_are_hidden_from_top_level_help() -> None:
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert " l9 " not in result.output
    assert " slim " not in result.output


def test_l9_send_rejects_invalid_kind_before_publishing(monkeypatch: pytest.MonkeyPatch) -> None:
    called = False

    def _fake_publish(*_a, **_k):
        nonlocal called
        called = True

    monkeypatch.setattr(wire, "publish_once", _fake_publish)

    result = runner.invoke(app, ["l9", "send", "--as", "avery", "--kind", "not-a-kind"])
    assert result.exit_code == 2
    assert not called


def test_l9_send_rejects_mismatched_subkind_before_publishing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    called = False

    def _fake_publish(*_a, **_k):
        nonlocal called
        called = True

    monkeypatch.setattr(wire, "publish_once", _fake_publish)

    result = runner.invoke(
        app,
        ["l9", "send", "--as", "avery", "--kind", "exchange", "--subkind", "converged"],
    )
    assert result.exit_code == 2
    assert not called


def test_l9_send_builds_envelope_and_publishes(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict = {}

    async def _fake_publish(**kwargs):
        captured.update(kwargs)

    monkeypatch.setattr(wire, "publish_once", _fake_publish)

    result = runner.invoke(
        app,
        [
            "l9",
            "send",
            "--as",
            "@avery",
            "--kind",
            "commit",
            "--subkind",
            "resolved",
            "--to",
            "bob, @rowan",
            "--parents",
            "p1,p2",
            "--data",
            '{"assignments": {"cap": "30"}}',
        ],
    )
    assert result.exit_code == 0, result.output
    assert captured["room"] == "demo"
    assert captured["handle"] == "avery"

    content = l9.parse(captured["payload"])
    assert content is not None
    assert l9.kind_of(content) == "commit"
    assert content["l9"]["header"]["subkind"] == "resolved"
    assert content["l9"]["header"]["message"]["parents"] == ["p1", "p2"]
    assert l9.recipients_of(content) == ["bob", "rowan"]
    assert l9.payload_data_of(content) == {"assignments": {"cap": "30"}}


def test_l9_send_rejects_non_object_data(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(wire, "publish_once", lambda **_k: None)
    result = runner.invoke(
        app,
        ["l9", "send", "--as", "avery", "--kind", "exchange", "--data", "[1, 2, 3]"],
    )
    assert result.exit_code == 2


def test_l9_send_surfaces_slim_send_error(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _boom(**_k):
        raise SlimSendError("SLIM node unreachable at http://x")

    monkeypatch.setattr(wire, "publish_once", _boom)
    result = runner.invoke(app, ["l9", "send", "--as", "avery", "--kind", "exchange"])
    assert result.exit_code == 1
    assert "unreachable" in result.output


def test_slim_send_requires_exactly_one_of_text_or_json() -> None:
    result = runner.invoke(app, ["slim", "send", "--as", "avery"])
    assert result.exit_code == 2

    result = runner.invoke(app, ["slim", "send", "--as", "avery", "--text", "hi", "--json", "{}"])
    assert result.exit_code == 2


def test_slim_send_publishes_raw_text(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict = {}

    async def _fake_publish(**kwargs):
        captured.update(kwargs)

    monkeypatch.setattr(wire, "publish_once", _fake_publish)

    result = runner.invoke(app, ["slim", "send", "--as", "@avery", "--text", "hello channel"])
    assert result.exit_code == 0, result.output
    assert captured["handle"] == "avery"
    assert captured["room"] == "demo"
    assert captured["payload"] == b"hello channel"


def test_slim_send_publishes_raw_json(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict = {}

    async def _fake_publish(**kwargs):
        captured.update(kwargs)

    monkeypatch.setattr(wire, "publish_once", _fake_publish)

    result = runner.invoke(app, ["slim", "send", "--as", "avery", "--json", '{"anything": true}'])
    assert result.exit_code == 0, result.output
    assert json.loads(captured["payload"]) == {"anything": True}


def test_slim_send_rejects_invalid_json() -> None:
    result = runner.invoke(app, ["slim", "send", "--as", "avery", "--json", "{not json"])
    assert result.exit_code == 2
