# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""What an engine says when it can't think because the hub has no model set.

The engines that think (personas, workers, the synthesizer, the verifier and
hello) share one model, the engines' model. People's own agents don't use it.
When an engine's turn fails on a hub with no model set, it says that, and where
to set one, rather than "Pi turn timed out or errored". It isn't checked before
a turn: Pi can also think with a login or key of its own the hub doesn't see,
and a check up front would stop an engine that works.
"""

from __future__ import annotations

NO_MODEL_TEXT = (
    "The hub has no model set, so I can't answer. Set one in Settings → Engines' model, "
    "or with `mycelium config set llm.model` and `mycelium config set llm.api_key`, "
    "then `mycelium config apply`."
)


def configured() -> bool:
    """Whether the hub has a model to think with: a key, or an address for a
    local one."""
    from app.services.llm_health import get_config_status

    return get_config_status().configured


def failed_turn(otherwise: str) -> str:
    """What an engine says when its turn failed: that the hub has no model set,
    when it hasn't, else ``otherwise``."""
    return otherwise if configured() else NO_MODEL_TEXT
