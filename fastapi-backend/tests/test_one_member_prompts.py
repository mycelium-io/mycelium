# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""A prompt code builds for one member mentions that member alone.

Nothing strips ``@`` from what is posted (``asks.py``), so wherever code writes
the text, writing a bare ``@`` only for whoever is asked is the code's job: a
turn to alice that names bob bare would wake bob in the middle of it. These
check each prompt the conductor builds for one member.
"""

from __future__ import annotations

import pytest

from app.services import protocols
from app.services.persister import parse_mentions


@pytest.mark.parametrize("name", protocols.builtin_names())
def test_no_built_in_flow_step_names_anyone_bare(name: str):
    # A step's prompt goes to the member the step addresses; what the flow
    # itself writes names members by role, never with a bare @.
    flow = protocols.builtin(name)
    assert flow is not None
    for step in flow.steps:
        assert parse_mentions(step.prompt) == [], f"{name}/{step.id}"
