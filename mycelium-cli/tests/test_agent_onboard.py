# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Julia Valenti

"""`mycelium agent add` brownfield onboarding: discovery, batch-adopt, the
non-interactive guard, and the create/add split."""

from __future__ import annotations

import json

import pytest
from typer.testing import CliRunner

from mycelium.integrations.openclaw import OpenClawIntegration

runner = CliRunner()


def test_discover_local_agents_parses_openclaw_json(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    state = tmp_path / ".openclaw"
    state.mkdir()
    (state / "openclaw.json").write_text(
        json.dumps(
            {
                "agents": {
                    "defaults": {"model": {"primary": "anthropic/sonnet"}},
                    "list": [
                        {"id": "zeta", "model": "anthropic/haiku", "workspace": "/w/z"},
                        # newer builds use the structured {primary: ...} form
                        {"id": "alpha", "model": {"primary": "anthropic/opus"}},
                        {"id": ""},  # junk — skipped
                        "not-a-dict",  # junk — skipped
                    ],
                }
            }
        )
    )
    monkeypatch.setattr(
        "mycelium.integrations.openclaw.dispatch._openclaw_state_dir",
        lambda _profile: state,
    )

    agents = OpenClawIntegration().discover_local_agents()
    ids = [a["id"] for a in agents]
    # sorted, implicit `main` always present, junk dropped
    assert ids == ["alpha", "main", "zeta"]
    by_id = {a["id"]: a for a in agents}
    assert by_id["alpha"]["model"] == "anthropic/opus"  # dict flattened
    assert by_id["zeta"]["workspace"] == "/w/z"


def test_discover_local_agents_missing_config_is_empty(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "mycelium.integrations.openclaw.dispatch._openclaw_state_dir",
        lambda _profile: tmp_path / "nope",
    )
    assert OpenClawIntegration().discover_local_agents() == []


def test_register_adopted_batch_restarts_gateway_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    impl = OpenClawIntegration()
    chan_calls: list[tuple[str, str]] = []
    restarts: list[int] = []

    monkeypatch.setattr(
        impl,
        "_register_channel",
        lambda *, room, agent_id, **_: chan_calls.append((room, agent_id)),
    )
    monkeypatch.setattr(impl, "restart_gateway", lambda: restarts.append(1))

    impl.register_adopted_batch(["a", "b", "c"], room="demo", backend_url="http://hub:8000")

    # one channel write per agent, into the same room — and ONE restart total
    assert chan_calls == [("demo", "a"), ("demo", "b"), ("demo", "c")]
    assert restarts == [1]


def test_agent_add_non_interactive_without_handle_errors() -> None:
    """CliRunner stdin/stdout aren't a TTY — bare `agent add` must refuse with
    guidance instead of hanging on a picker or silently doing nothing."""
    from mycelium.cli import app

    result = runner.invoke(app, ["agent", "add"])
    assert result.exit_code == 1
    assert "non-interactive" in result.output
    assert "mycelium agent create" in result.output  # points at greenfield


def test_agent_create_has_no_openclaw_agent_flag() -> None:
    """`create` is greenfield only — the adopt-only --openclaw-agent flag must
    live on `add`, not `create`."""
    from mycelium.cli import app

    create_help = runner.invoke(app, ["agent", "create", "--help"]).output
    add_help = runner.invoke(app, ["agent", "add", "--help"]).output
    assert "--openclaw-agent" not in create_help
    assert "--cwd" in create_help
    assert "[HANDLE]" in add_help  # handle is optional on add (picker)
