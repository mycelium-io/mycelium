# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""mycelium hub settings: what a hub says it is set up with, in words."""

from __future__ import annotations

from typing import Any

from mycelium.commands.hub import _settings_lines
from mycelium_backend_client.models import HubSettings


def _settings(**over: Any) -> HubSettings:
    """A hub's settings answer, whole, with ``over`` laid on top."""
    return HubSettings.from_dict(
        {
            "model": {
                "model": "anthropic/claude-sonnet-4-6",
                "provider": "anthropic",
                "has_key": True,
                "custom_endpoint": False,
            },
            "experiences": [
                {
                    "id": "patterns-explorer",
                    "title": "Patterns Explorer",
                    "description": "",
                    "open": "/patterns",
                    "unit": "scenario",
                    "scenarios": 3,
                }
            ],
            "personas_only": True,
            "share_usage": False,
            "workers": {"tools": True, "turn_timeout_s": 600.0, "max_turns_per_room": 60},
            "dependency_gate": False,
            "patterns_inline": True,
            "sign_in": False,
            "voice": {"enabled": False, "model": "fast"},
            "editing": {"may_edit": True, "can_restart": True},
            **over,
        }
    )


def test_it_says_the_model_and_whether_a_key_is_set():
    lines = _settings_lines(_settings())
    assert lines[0].split() == ["Model", "anthropic/claude-sonnet-4-6", "(key", "set)"]
    assert "Patterns Explorer: 3 scenarios, at /patterns" in lines[1]
    assert lines[2].endswith("yes")
    assert lines[3].endswith("not shared")


def test_a_hub_with_nothing_set_says_so():
    nothing = _settings(
        model={"model": None, "has_key": False, "custom_endpoint": False}, experiences=[]
    )
    lines = _settings_lines(nothing)
    assert "none set (no key)" in lines[0]
    assert lines[1].split() == ["Experiences", "none"]
