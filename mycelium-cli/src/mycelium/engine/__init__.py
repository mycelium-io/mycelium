# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""The host-side cognition-engine mediation core (backend-side only).

The first-party SAO mediator: the NEGMAS core (``mediator``), the Pi LLM session
(``pi_session``), the fuzzy offer snap (``offer_snap``), and the SLIM drive loop
(``runtime``). The heavy dep (negmas) comes from the ``mycelium[engine]`` extra.

Not wired to a CLI runtime entry point; the backend drives it directly.
"""
