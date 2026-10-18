# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""Every command the Mac app answers checks who is calling.

The hub's own UI in the app's window may call into it
(``mycelium-desktop/src-tauri/capabilities/own-hub-ui.json``), so the
capability no longer keeps a hub's page out: each ``#[tauri::command]`` has to
refuse a page itself, with ``local_only`` (the app's own pages) or
``own_ui_only`` (this Mac's own hub UI). This reads the Rust and fails on a
command that does neither. CI doesn't build the app, so the check is here.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[2] / "mycelium-desktop" / "src-tauri" / "src"
GUARDS = ("local_only(", "own_ui_only(")
#: What ``own_ui_only`` may answer: nothing beyond these two.
OWN_UI = {"this_machine", "choose_agent_folder"}

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
def test_only_the_folder_dialog_and_its_machine_answer_the_hubs_page() -> None:
    open_to_hub = {name for name, body in _commands().items() if "own_ui_only(" in body}
    assert open_to_hub == OWN_UI
