# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""Scenario registry for ``mycelium demo``.

Each entry is just a *pointer* into the public ``agent-personas`` dataset plus a
one-line seed task — the actual persona text is fetched live at run time
(``demo.py``), never mirrored here. There is no recorded transcript: the demo
creates real agents and lets them negotiate for real.

Persona files live at
``https://github.com/mycelium-io/agent-personas`` under ``preferences/``.
"""

from __future__ import annotations

from typing import Any

# Raw base for fetching persona prose. Pinned to the default branch.
PERSONAS_RAW_BASE = "https://raw.githubusercontent.com/mycelium-io/agent-personas/main"


_EX07: dict[str, Any] = {
    "id": "ex07_investment_portfolio",
    "title": "Investment portfolio rebalance",
    "tagline": "Growth vs. volatility — three desks rebalance the model portfolio.",
    "room": "demo-investment-portfolio",
    "task": (
        "Rebalance the model portfolio for next quarter. Reach consensus on the "
        "target equity allocation, rebalance pace, downside hedging, and cash buffer."
    ),
    "agents": [
        {"handle": "growth", "persona": "preferences/ex07_growth_agent.yaml"},
        {"handle": "risk", "persona": "preferences/ex07_risk_agent.yaml"},
        {"handle": "execution", "persona": "preferences/ex07_execution_agent.yaml"},
    ],
}

_EX09: dict[str, Any] = {
    "id": "ex09_ci_cd_release",
    "title": "CI/CD release decision",
    "tagline": "Deadline vs. test gates vs. error budget.",
    "room": "demo-ci-cd-release",
    "task": (
        "Release 4.2 is cut but the error rate is up and regression has flaky "
        "failures. Reach consensus on release timing, test gates, and rollout strategy."
    ),
    "agents": [
        {"handle": "deploy", "persona": "preferences/ex09_deploy_agent.yaml"},
        {"handle": "qa", "persona": "preferences/ex09_qa_agent.yaml"},
        {"handle": "sre", "persona": "preferences/ex09_sre_agent.yaml"},
    ],
}

_EX04: dict[str, Any] = {
    "id": "ex04_travel_planning",
    "title": "Trip planning to Italy",
    "tagline": "Budget vs. comfort vs. sightseeing.",
    "room": "demo-travel-planning",
    "task": (
        "Plan a 7-day Italy trip for two on a $4k budget. Reach consensus on "
        "flight class, hotel tier, and daily pace."
    ),
    "agents": [
        {"handle": "flight", "persona": "preferences/ex04_flight_agent.yaml"},
        {"handle": "stay", "persona": "preferences/ex04_stay_agent.yaml"},
        {"handle": "itinerary", "persona": "preferences/ex04_itinerary_agent.yaml"},
    ],
}


SCENARIOS: dict[str, dict[str, Any]] = {
    _EX07["id"]: _EX07,
    _EX09["id"]: _EX09,
    _EX04["id"]: _EX04,
}

DEFAULT_SCENARIO = _EX07["id"]


def list_scenarios() -> list[dict[str, Any]]:
    """Scenarios in display order (default first)."""
    ordered = [SCENARIOS[DEFAULT_SCENARIO]]
    ordered += [s for sid, s in SCENARIOS.items() if sid != DEFAULT_SCENARIO]
    return ordered
