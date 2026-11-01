# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""Every command the desktop app answers checks who is calling.

The hub's own UI in the app's window may call into it
(``mycelium-desktop/src-tauri/capabilities/own-hub-ui.json``), so the
capability no longer keeps a hub's page out: each ``#[tauri::command]`` has to
refuse a page itself, with ``local_only`` (the app's own pages) or
``own_ui_only`` (the hub UI of the app's own hub). This reads the Rust and fails on a
command that does neither. CI doesn't build the app, so the check is here.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[2] / "mycelium-desktop" / "src-tauri" / "src"
GUARDS = ("local_only(", "own_ui_only(")
#: What ``own_ui_only`` may answer, and nothing beyond it. ``agent_screen``
#: hands the app's own hub UI what a terminal on this machine shows, which is
#: why it's here and never a hub route: a screen doesn't leave the machine.
OWN_UI = {"this_machine", "choose_agent_folder", "agent_screen"}
#: The app's own Settings pages, which are pages of the UI's Settings: where
#: rooms live and start at login, the model, the agents' folder, experiences,
#: the version, the health check and its log. Each answers the app's bundled
#: pages too (first run), and the ones that change what the app is (``start``
#: with another hub or folder, ``save_model``, ``switch_version``) ask on the
#: machine first, in a dialog no page can answer (``confirmed_here``).
OWN_UI |= {
    "get_state",
    "start",
    "get_autostart",
    "set_autostart",
    "scan_agents",
    "pick_folder",
    "run_doctor",
    "open_log",
    "get_model",
    "save_model",
    "get_experiences",
    "add_experience",
    "remove_experience",
    "get_hub_settings",
    "app_versions",
    "set_update_channel",
    "switch_version",
}
#: Of those, the ones that ask on the machine before they act from the UI.
ASKS_FIRST = {"start", "save_model", "switch_version"}

_COMMAND = re.compile(r"#\[tauri::command\]\s*(?:pub\s+)?(?:async\s+)?fn\s+(\w+)")


def _commands() -> dict[str, str]:
    """Each command's name and its body, up to the next top-level item."""
    found: dict[str, str] = {}
    for path in sorted(SRC.glob("*.rs")):
        text = path.read_text(encoding="utf-8")
        for m in _COMMAND.finditer(text):
            end = text.find("\n}\n", m.end())
            found[m.group(1)] = text[m.end() : end if end != -1 else len(text)]
    return found


@pytest.mark.skipif(not SRC.is_dir(), reason="the desktop app's source isn't in this checkout")
def test_every_app_command_refuses_a_page_it_does_not_answer() -> None:
    commands = _commands()
    assert len(commands) > 20, "no commands found; has the source moved?"
    unguarded = sorted(
        name for name, body in commands.items() if not any(g in body for g in GUARDS)
    )
    assert unguarded == [], (
        f"{unguarded} call neither local_only nor own_ui_only, so the hub's page could call them"
    )


@pytest.mark.skipif(not SRC.is_dir(), reason="the desktop app's source isn't in this checkout")
def test_the_ui_may_call_exactly_the_commands_named_for_it() -> None:
    open_to_hub = {name for name, body in _commands().items() if "own_ui_only(" in body}
    assert open_to_hub == OWN_UI


@pytest.mark.skipif(not SRC.is_dir(), reason="the desktop app's source isn't in this checkout")
def test_a_change_to_what_the_app_is_asks_on_the_machine_first() -> None:
    commands = _commands()
    asks = {name for name in OWN_UI if "confirmed_here(" in commands[name]}
    assert asks == ASKS_FIRST


def _allow(command: str) -> str:
    return "allow-" + command.replace("_", "-")


@pytest.mark.skipif(not SRC.is_dir(), reason="the desktop app's source isn't in this checkout")
def test_tauri_lets_each_page_call_what_it_should_and_no_more() -> None:
    # Tauri refuses the hub's UI (a remote origin) any app command no
    # capability names, and once build.rs declares the commands it checks the
    # app's own pages too. So: every command declared, all of them granted to
    # the local pages, and exactly the own_ui_only ones to the hub's UI.
    tauri = SRC.parent
    declared = set(re.findall(r'^\s*"(\w+)",$', (tauri / "build.rs").read_text(), re.M))
    assert declared == set(_commands()), "build.rs's COMMANDS must list every #[tauri::command]"

    def granted(capability: str) -> set[str]:
        data = json.loads((tauri / "capabilities" / f"{capability}.json").read_text())
        return {p for p in data["permissions"] if isinstance(p, str) and p.startswith("allow-")}

    assert granted("default") == {_allow(c) for c in declared}
    assert granted("own-hub-ui") == {_allow(c) for c in OWN_UI}
