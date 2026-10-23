# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""``mycelium.integrations.agents``: the one place an agent CLI is named."""

from __future__ import annotations

from pathlib import Path

import pytest

from mycelium.integrations import agents, get_integration

PACKAGE = Path(agents.__file__).resolve().parents[2]


def test_each_cli_is_listed_once():
    ids = [k.id for k in agents.KNOWN]
    assert len(ids) == len(set(ids))


def test_a_cli_with_nothing_of_its_own_adds_nothing():
    gemini = agents.of_kind("gemini")
    assert gemini.launch_args() == []
    assert gemini.blocked_hint() is None
    unknown = agents.of_kind("someday")
    assert (unknown.id, unknown.launch_args(), unknown.adapter) == ("someday", [], "claude_code")


CLAUDE_HELP = (
    '  --permission-mode <mode>  (choices: "acceptEdits", "auto", "bypassPermissions", "plan")'
)
OLD_CLAUDE_HELP = (
    '  --permission-mode <mode>  (choices: "acceptEdits", "bypassPermissions", "plan")'
)
CODEX_HELP = (
    "  -s, --sandbox <SANDBOX_MODE>\n"
    "          [possible values: read-only, workspace-write, danger-full-access]\n"
    "      --approve-for-me\n          Route approval requests through automatic review"
)


def _installed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, **helps: str) -> None:
    """Stand-in CLIs on PATH whose ``--help`` prints what's given, and nothing else there."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    for name, text in helps.items():
        exe = bin_dir / name
        exe.write_text(f"#!/bin/sh\n/bin/cat <<'EOF'\n{text}\nEOF\n")
        exe.chmod(0o755)
    monkeypatch.setenv("PATH", str(bin_dir))


def test_claude_is_started_allowed_mycelium_in_its_auto_mode(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    _installed(tmp_path, monkeypatch, claude=CLAUDE_HELP)
    claude = agents.of_kind("claude")
    args = claude.launch_args()
    assert args == ["--allowedTools", "Bash(mycelium:*)", "--permission-mode", "auto"]
    assert "Claude Code asks before" in (claude.blocked_hint() or "")
    # A restart that resumes its session keeps the mode: resuming adds to these.
    assert "--dangerously-skip-permissions" not in args


def test_an_older_claude_without_auto_mode_starts_as_before(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    _installed(tmp_path, monkeypatch, claude=OLD_CLAUDE_HELP)
    claude = agents.of_kind("claude")
    assert claude.launch_args() == ["--allowedTools", "Bash(mycelium:*)"]


def test_codex_sandbox_lets_mycelium_reach_the_hub_and_write_only_its_agent_state(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setenv("HOME", str(tmp_path))
    _installed(tmp_path, monkeypatch, codex=CODEX_HELP)
    args = agents.of_kind("codex").launch_args()
    state = tmp_path / ".mycelium" / "agent-state"
    assert args == [
        # It sets workspace-write itself, so that sandbox is chosen whatever
        # the person's config or the folder's trust says.
        "--approve-for-me",
        "-c",
        "sandbox_workspace_write.network_access=true",
        "--add-dir",
        str(state),
    ]
    assert state.is_dir()
    # Never the whole folder: its config, herdr registry and the runner's
    # approval files stay out of an agent's reach.
    assert str(tmp_path / ".mycelium") not in args
    # Never the bypass or full access.
    assert "danger-full-access" not in args
    assert not any("dangerously" in a for a in args)


def test_approve_for_me_never_comes_with_the_flags_codex_refuses_beside_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """Codex declares ``--approve-for-me`` in conflict with ``--sandbox`` and
    ``--ask-for-approval``: passed together, it prints an argument error and exits."""
    monkeypatch.setenv("HOME", str(tmp_path))
    _installed(tmp_path, monkeypatch, codex=CODEX_HELP)  # offers all three
    args = agents.of_kind("codex").launch_args()
    assert "--approve-for-me" in args
    assert not {"--sandbox", "-s", "--ask-for-approval", "-a"} & set(args)
    assert not any(a.startswith(("sandbox_mode=", "approval_policy=")) for a in args)


def test_an_older_codex_without_auto_review_picks_the_sandbox_and_asks_on_request(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setenv("HOME", str(tmp_path))
    _installed(tmp_path, monkeypatch, codex="  -s, --sandbox <SANDBOX_MODE>")
    args = agents.of_kind("codex").launch_args()
    assert "--approve-for-me" not in args
    assert args[:4] == ["--sandbox", "workspace-write", "--ask-for-approval", "on-request"]


def test_a_codex_under_nvm_is_asked_about_its_flags_with_its_node_on_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """Found only in nvm's folder, and runnable only with that folder on PATH:
    a Node CLI's ``#!/usr/bin/env node`` needs the node installed beside it.
    Asked any other way, it says nothing, and Codex would start without the
    flags it has."""
    from mycelium.runner import frameworks

    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("PATH", str(tmp_path / "empty"))  # the runner's own: no codex
    nvm = tmp_path / ".nvm" / "versions" / "node" / "v24.1.0" / "bin"
    nvm.mkdir(parents=True)
    node = nvm / "fakenode"  # the interpreter, only in nvm's folder
    node.write_text(f"#!/bin/sh\n/bin/cat <<'EOF'\n{CODEX_HELP}\nEOF\n")
    node.chmod(0o755)
    codex = nvm / "codex"
    codex.write_text("#!/usr/bin/env fakenode\n")
    codex.chmod(0o755)
    monkeypatch.setattr(frameworks, "install_dirs", lambda: [nvm])

    args = agents.of_kind("codex").launch_args()
    assert args[0] == "--approve-for-me"


def _codex_login(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *, said: str, code: int) -> None:
    """A stand-in codex whose ``login status`` says ``said`` and exits ``code``."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    exe = bin_dir / "codex"
    exe.write_text(
        '#!/bin/sh\nif [ "$1 $2" = "login status" ]; then\n'
        f"  echo '{said}' >&2\n  exit {code}\nfi\nexit 0\n"
    )
    exe.chmod(0o755)
    monkeypatch.setenv("PATH", str(bin_dir))


def test_a_codex_that_isnt_signed_in_says_so_before_it_starts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """Not signed in, Codex opens on screens that only take Enter, which herdr
    reads as ready: the start is stopped before it begins, with what to do."""
    _codex_login(tmp_path, monkeypatch, said="Not logged in", code=1)
    reason = agents.of_kind("codex").not_ready()
    assert reason is not None
    assert "isn't signed in" in reason
    assert "Then try again." in reason


def test_a_signed_in_codex_or_one_that_cant_say_starts_as_usual(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    _codex_login(tmp_path, monkeypatch, said="Logged in using ChatGPT", code=0)
    assert agents.of_kind("codex").not_ready() is None
    # An older Codex without the command, or any other trouble, is left for the
    # start itself to report rather than guessed at here.
    _codex_login(tmp_path, monkeypatch, said="error: unrecognized subcommand 'status'", code=2)
    assert agents.of_kind("codex").not_ready() is None
    # And a CLI with nothing to set up never is.
    assert agents.of_kind("claude").not_ready() is None


def test_codex_knows_its_welcome_after_signing_in_from_its_sign_in():
    codex = agents.of_kind("codex")
    # Signed in in the pane, or with an auth.json its app server didn't take:
    # nothing to choose, so Enter gets past it.
    welcome = codex.first_run("✓ Signed in with your ChatGPT account\n\n  Press enter to continue")
    assert welcome is not None
    assert welcome.key == "enter"
    # Its sign-in menu ends with "Press enter to continue" too: Enter there would
    # choose a sign-in, so only the person answers it.
    menu = codex.first_run(
        "> 1. Sign in with ChatGPT\n  2. Sign in with Device Code\n  Press enter to continue"
    )
    assert menu is not None
    assert menu.key is None
    assert "sign in" in menu.what
    assert codex.first_run("Press enter to continue") is None
    assert codex.first_run("› Ask Codex to do anything") is None
    # A CLI with no first-run screens of its own sees none.
    assert agents.of_kind("claude").first_run("Sign in with ChatGPT") is None


def test_a_codex_without_the_sandbox_flag_picks_the_mode_through_its_config(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setenv("HOME", str(tmp_path))
    _installed(tmp_path, monkeypatch, codex="  -c, --config <key=value>")
    args = agents.of_kind("codex").launch_args()
    assert args[:4] == [
        "-c",
        'sandbox_mode="workspace-write"',
        "-c",
        'approval_policy="on-request"',
    ]
    assert "--sandbox" not in args


def test_what_an_agent_writes_lives_in_the_agent_state_folder(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    from mycelium import agent_credentials
    from mycelium.commands import participate
    from mycelium.config import MyceliumConfig

    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.delenv(agent_credentials.CREDENTIAL_STORE_ENV, raising=False)
    state = MyceliumConfig.get_agent_state_dir()
    assert participate._pending_file().parent == state  # noqa: SLF001
    assert agent_credentials.token_cache_path("scout").is_relative_to(state)


@pytest.mark.parametrize(
    ("framework", "adapter"),
    [
        ("cursor", "cursor"),
        ("claude", "claude_code"),
        ("codex", "claude_code"),
        (None, "claude_code"),
    ],
)
def test_each_cli_is_recorded_under_its_manifest_family(framework, adapter):
    assert agents.adapter_for(framework) == adapter
    assert get_integration(adapter).name == adapter


@pytest.mark.parametrize(
    "module",
    [
        "runner/hosts.py",
        "runner/daemon.py",
        "integrations/herdr/bridge.py",
        "commands/swarm.py",
        "machine.py",
    ],
)
def test_the_generic_paths_name_no_cli(module: str):
    text = (PACKAGE / module).read_text()
    for said in ("Claude Code", "--allowedTools", "Cursor Agent"):
        assert said not in text, f"{module} names {said!r}; it belongs in integrations/agents"
