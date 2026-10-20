# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""The nightly agent CLI smoke test, as far as it runs without herdr.

The nightly job (``agent-clis`` in ``nightly.yml``) runs the rest against
real CLIs; what's checked here is the plan it builds its matrix from, the
checks that end before herdr, and the issue text it writes.
"""

from __future__ import annotations

import json

from mycelium.integrations import agents
from mycelium.runner import smoke


def test_the_plan_covers_every_cli_with_an_install_command() -> None:
    plan = smoke.plan()
    assert [p["cli"] for p in plan] == [k.id for k in agents.KNOWN]
    assert all(p["install"] for p in plan), [p["cli"] for p in plan if not p["install"]]
    json.dumps(plan)  # the job reads it as JSON


def test_a_cli_not_in_the_table_fails_as_unknown() -> None:
    result = smoke.run("someday")
    assert not result.ok
    assert result.checks[0].name == "known"


def test_a_cli_that_isnt_installed_says_so(monkeypatch) -> None:
    monkeypatch.setattr(smoke.shutil, "which", lambda _b: None)
    result = smoke.run("codex")
    assert not result.ok
    assert [c.name for c in result.checks] == ["installed"]
    assert "codex" in result.checks[0].detail


def test_a_cli_herdr_doesnt_start_passes_without_starting(monkeypatch) -> None:
    monkeypatch.setattr(smoke.shutil, "which", lambda b: f"/usr/bin/{b}")
    monkeypatch.setattr(smoke, "_version", lambda _b: "1.0")
    result = smoke.run("aider")
    assert result.ok
    assert result.checks[-1].name == "started"


def test_the_issue_names_the_cli_the_check_and_shows_its_screen(tmp_path) -> None:
    bad = smoke.Result(cli="codex", name="Codex", version="0.163.0", screen="Unknown option --x")
    bad.check("shell", ok=True)
    bad.check("starts", ok=False, detail="it didn't come up as an agent")
    good = smoke.Result(cli="claude", name="Claude Code")
    good.check("starts", ok=True)
    path = tmp_path / "codex.json"
    path.write_text(json.dumps(smoke.asdict(bad)))
    text = smoke.markdown([smoke._load(path), good])
    assert "### Codex (0.163.0)" in text
    assert "**starts**: it didn't come up as an agent" in text
    assert "Unknown option --x" in text
    assert "Claude Code" not in text
    assert smoke.markdown([good]).startswith("Every agent CLI started")


def test_a_live_result_never_holds_a_key_it_was_given(monkeypatch) -> None:
    """A result becomes an artifact and can open a public issue, so a key the
    CLI echoed (its config, a header in an error) is taken out first."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-secret-value")
    monkeypatch.setenv("ANTHROPIC_MODEL", "claude-haiku-4-5")
    result = smoke.Result(cli="claude", name="Claude Code", screen="key: sk-ant-secret-value")
    result.check("answers in the room", ok=False, detail="401 for sk-ant-secret-value")
    cleaned = smoke.redact(result, ["ANTHROPIC_API_KEY", "ANTHROPIC_MODEL"])
    assert cleaned.screen == "key: ***"
    assert cleaned.checks[0].detail == "401 for ***"
    # A model name isn't a secret, and stays readable.
    assert smoke.redact(
        smoke.Result(cli="c", name="c", screen="claude-haiku-4-5"), ["ANTHROPIC_MODEL"]
    ).screen == ("claude-haiku-4-5")
