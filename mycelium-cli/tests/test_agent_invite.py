# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""``mycelium agent invite`` prints what the app's Open session gives."""

from __future__ import annotations

from mycelium.commands.agent import HARNESS_SPEC_URL, handoff_prompt


def test_the_prompt_joins_with_the_code_and_points_at_the_spec() -> None:
    prompt = handoff_prompt("https://hub.example.com", "atlas", "muse", "k7mq-2xpa-9vtd", "14:32")
    assert "room `atlas` on the hub at https://hub.example.com, as @muse" in prompt
    assert "mycelium join k7mq-2xpa-9vtd --hub https://hub.example.com" in prompt
    assert "until 14:32" in prompt
    assert "mycelium room messages atlas --limit 20" in prompt
    assert HARNESS_SPEC_URL in prompt
    assert "mycelium login" not in prompt
